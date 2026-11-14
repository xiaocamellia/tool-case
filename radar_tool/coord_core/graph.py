"""图构建、路径搜索、矩阵合成与路径回显（求解层）。

图语义：节点 = 坐标系；记录给出 ``T_from_to``（``p_from = T · p_to``），
即数量从 ``to`` 流向 ``from`` 的有向边，反向边自动取逆。
``query(A, B)`` 沿 B→A 的路径逐边左乘得到 ``T_A_B``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import breadth_first_order, dijkstra

from ..errors import ValidationError
from .conventions import STATUS_PRIORITY
from .schema import LedgerDocument, TransformRecord
from .transforms import compose_transforms, invert_transform

EDGE_STRATEGIES = ("min_error", "min_hops")


@dataclass(frozen=True)
class PathSegment:
    """路径中的一段（一条实际入账的变换记录，方向已注明）。"""

    record_id: str
    from_frame: str          # 该段矩阵的输出系（数量流入端）
    to_frame: str            # 该段矩阵的输入系
    sigma_t_m: float
    sigma_r_arcsec: float
    status: str
    source: str
    reversed: bool           # True 表示使用了记录的逆

    def label(self) -> str:
        arrow = f"{self.to_frame} → {self.from_frame}"
        suffix = "（取逆）" if self.reversed else ""
        return f"{arrow}{suffix}"


@dataclass
class TransformPath:
    """一条合成变换及其路径回显。"""

    source: str                       # 被变换量所在系（B）
    target: str                       # 结果所在系（A）
    matrix: np.ndarray                # T_target_source
    frames: List[str] = field(default_factory=list)   # [B, ..., A]
    segments: List[PathSegment] = field(default_factory=list)

    @property
    def hops(self) -> int:
        return len(self.segments)

    def sigma_total(self) -> Tuple[float, float]:
        """RSS 合成 (σ_t_m, σ_r_arcsec)。"""
        t_var = sum(segment.sigma_t_m ** 2 for segment in self.segments)
        r_var = sum(segment.sigma_r_arcsec ** 2 for segment in self.segments)
        return float(np.sqrt(t_var)), float(np.sqrt(r_var))


def select_records(
    document: LedgerDocument,
    status: Optional[str] = None,
) -> List[TransformRecord]:
    """按状态过滤挑选参与求解的记录。

    - ``status=None``：每组 ``(from, to)`` 取优先级最高者（obsolete 永不自动选中）；
    - ``status`` 指定：只取该状态记录，同状态多条时取优先级规则下的稳定首条（按 id 排序）。
    """
    if status is not None:
        chosen = [record for record in document.transforms if record.status == status]
        best: Dict[Tuple[str, str], TransformRecord] = {}
        for record in sorted(chosen, key=lambda item: item.id):
            key = (record.from_frame, record.to_frame)
            best[key] = record
        return list(best.values())

    best = {}
    for record in document.transforms:
        priority = STATUS_PRIORITY.get(record.status, -1)
        if priority <= 0:
            continue
        key = (record.from_frame, record.to_frame)
        current = best.get(key)
        if current is None or priority > STATUS_PRIORITY[current.status]:
            best[key] = record
        elif priority == STATUS_PRIORITY[current.status] and record.id < current.id:
            best[key] = record
    return list(best.values())


class TransformGraph:
    """坐标系变换图：邻接矩阵 + 路径搜索 + 合成。"""

    def __init__(self, document: LedgerDocument, status: Optional[str] = None):
        self.document = document
        self.status = status
        self.records: List[TransformRecord] = select_records(document, status)
        self.frames: List[str] = [frame.id for frame in document.frames]
        self._index: Dict[str, int] = {frame_id: i for i, frame_id in enumerate(self.frames)}
        self._edges: Dict[Tuple[int, int], Tuple[np.ndarray, PathSegment]] = {}
        self._matrix_cache: Dict[str, np.ndarray] = {}
        self._build()

    # --- 构建 ---

    def _build(self) -> None:
        meta = self.document.meta
        for record in self.records:
            if record.from_frame not in self._index or record.to_frame not in self._index:
                continue
            matrix = record.homogeneous(meta)
            segment = PathSegment(
                record_id=record.id,
                from_frame=record.from_frame,
                to_frame=record.to_frame,
                sigma_t_m=record.sigma.t,
                sigma_r_arcsec=record.sigma.r_arcsec,
                status=record.status,
                source=record.source,
                reversed=False,
            )
            self._add_edge(record.to_frame, record.from_frame, matrix, segment)
            inverse_segment = PathSegment(
                record_id=record.id,
                from_frame=record.to_frame,
                to_frame=record.from_frame,
                sigma_t_m=record.sigma.t,
                sigma_r_arcsec=record.sigma.r_arcsec,
                status=record.status,
                source=record.source,
                reversed=True,
            )
            self._add_edge(record.from_frame, record.to_frame, invert_transform(matrix), inverse_segment)

    def _add_edge(self, source: str, target: str, matrix: np.ndarray, segment: PathSegment) -> None:
        key = (self._index[source], self._index[target])
        self._edges[key] = (matrix, segment)

    # --- 权重 ---

    @staticmethod
    def _edge_weight(matrix: np.ndarray, segment: PathSegment, strategy: str) -> float:
        if strategy == "min_hops":
            return 1.0
        # min_error：平移 σ(mm) 与旋转 σ(″) 的加权组合（设计文档 C2）
        return float(np.hypot(segment.sigma_r_arcsec, segment.sigma_t_m * 1000.0))

    def _sparse_graph(self, strategy: str) -> csr_matrix:
        n = len(self.frames)
        rows, cols, data = [], [], []
        for (row, col), (matrix, segment) in self._edges.items():
            rows.append(row)
            cols.append(col)
            data.append(self._edge_weight(matrix, segment, strategy))
        return csr_matrix((data, (rows, cols)), shape=(n, n))

    # --- 路径搜索 ---

    def find_path(self, source: str, target: str, strategy: str = "min_error") -> List[Tuple[int, int]]:
        """返回 source→target 的边索引序列。"""
        if strategy not in EDGE_STRATEGIES:
            raise ValidationError(f"未知路径策略: {strategy}，可选 {' / '.join(EDGE_STRATEGIES)}")
        self._require_frame(source)
        self._require_frame(target)
        if source == target:
            return []
        start = self._index[source]
        goal = self._index[target]
        if strategy == "min_hops":
            graph = self._sparse_graph("min_hops")
            order, predecessors = breadth_first_order(
                graph, directed=True, i_start=start, return_predecessors=True
            )
        else:
            graph = self._sparse_graph("min_error")
            _, predecessors = dijkstra(graph, directed=True, indices=start, return_predecessors=True)
        if predecessors[goal] < 0:
            raise ValidationError(f"找不到从 {source} 到 {target} 的变换路径")
        path = []
        node = goal
        while node != start:
            previous = int(predecessors[node])
            if previous < 0:
                raise ValidationError(f"路径回溯失败：{source} → {target}")
            path.append((previous, node))
            node = previous
        path.reverse()
        return path

    def resolve(self, source: str, target: str, strategy: str = "min_error") -> TransformPath:
        """合成 ``T_target_source`` 并回显路径。"""
        self._require_frame(source)
        self._require_frame(target)
        if source == target:
            return TransformPath(source=source, target=target, matrix=np.eye(4),
                                 frames=[source], segments=[])
        edge_keys = self.find_path(source, target, strategy)
        matrices = []
        segments = []
        for key in edge_keys:
            matrix, segment = self._edges[key]
            matrices.append(matrix)
            segments.append(segment)
        # 边 (f_i, f_{i+1}) 的矩阵把 p_{f_i} 变到 f_{i+1} 系；
        # T_target_source = M_{k-1} · … · M_0，故按路径逆序左乘。
        matrix = compose_transforms(*reversed(matrices))
        frames = [source]
        for _key, segment in zip(edge_keys, segments):
            frames.append(segment.from_frame)
        return TransformPath(
            source=source,
            target=target,
            matrix=matrix,
            frames=frames,
            segments=segments,
        )

    # --- 工具 ---

    def _require_frame(self, frame_id: str) -> None:
        if frame_id not in self._index:
            raise ValidationError(f"坐标系不存在: {frame_id}")

    def all_pairs(self, strategy: str = "min_error") -> Dict[Tuple[str, str], TransformPath]:
        """全表预计算（C5），规模受 10 节限制（≤200 系）。"""
        result: Dict[Tuple[str, str], TransformPath] = {}
        for source in self.frames:
            for target in self.frames:
                if source == target:
                    continue
                try:
                    result[(source, target)] = self.resolve(source, target, strategy)
                except ValidationError:
                    continue
        return result

    def fundamental_cycles(self) -> List[List[Tuple[str, str, PathSegment]]]:
        """生成树 + 非树边枚举基本回路（D8）。

        返回若干回路，每个回路是边列表 ``[(u, v, segment), ...]``，
        沿回路方向逐边相乘应得到单位阵。
        """
        if not self.frames:
            return []
        undirected: Dict[str, List[str]] = {frame_id: [] for frame_id in self.frames}
        seen_pairs = set()
        edge_lookup: Dict[Tuple[str, str], Tuple[np.ndarray, PathSegment]] = {}
        for (row, col), payload in self._edges.items():
            u, v = self.frames[row], self.frames[col]
            edge_lookup[(u, v)] = payload
            pair = tuple(sorted((u, v)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            undirected[u].append(v)
            undirected[v].append(u)

        # BFS 生成树
        root = self.frames[0]
        parent: Dict[str, Optional[str]] = {root: None}
        order = [root]
        queue = [root]
        while queue:
            current = queue.pop(0)
            for neighbor in sorted(undirected[current]):
                if neighbor not in parent:
                    parent[neighbor] = current
                    order.append(neighbor)
                    queue.append(neighbor)

        def chain_to_root(node: str) -> List[str]:
            chain = [node]
            while parent[chain[-1]] is not None:
                chain.append(parent[chain[-1]])
            return chain

        cycles: List[List[Tuple[str, str, PathSegment]]] = []
        tree_edges = set()
        for node, dad in parent.items():
            if dad is not None:
                tree_edges.add(tuple(sorted((node, dad))))

        for pair in sorted(seen_pairs):
            if pair in tree_edges:
                continue
            u, v = pair
            chain_u = chain_to_root(u)
            chain_v = chain_to_root(v)
            # 找 u、v 到根路径的分叉点
            set_u = set(chain_u)
            lca = next(node for node in chain_v if node in set_u)
            # 回路：u → lca 沿树向上，lca → v 沿树向下，v → u 走非树边
            cycle: List[Tuple[str, str, PathSegment]] = []
            node = u
            while node != lca:
                dad = parent[node]
                cycle.append((node, dad, self._edge_between(node, dad)))
                node = dad
            branch = []
            node = v
            while node != lca:
                dad = parent[node]
                branch.append((dad, node, self._edge_between(dad, node)))
                node = dad
            cycle.extend(reversed(branch))
            cycle.append((v, u, self._edge_between(v, u)))
            cycles.append(cycle)
        return cycles

    def _edge_between(self, u: str, v: str) -> PathSegment:
        payload = self._edges.get((self._index[u], self._index[v]))
        if payload is None:
            raise ValidationError(f"回路边缺失: {u} → {v}")
        return payload[1]

    def edge_matrix(self, u: str, v: str) -> np.ndarray:
        payload = self._edges.get((self._index[u], self._index[v]))
        if payload is None:
            raise ValidationError(f"边不存在: {u} → {v}")
        return payload[0]
