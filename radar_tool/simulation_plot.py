"""Plotting mixins for the interferometer simulation panel."""

import numpy as np


class SimulationPlotMixin:
    def _plot_array_layout(self):
        """绘制3D阵列布局图（右手系：X=法线, Y=右, Z=上）"""
        if self.array_pos is None or not hasattr(self, "array_figure"):
            return

        from mpl_toolkits.mplot3d import Axes3D, art3d

        fig = self.array_figure
        fig.clear()
        ax = fig.add_subplot(111, projection="3d")

        pos = self.array_pos  # pos[:,0]=Y, pos[:,1]=Z

        # 阵元位于 Y-Z 平面 (X=0)
        xs = np.zeros(len(pos))  # X=0 （法线方向）
        ys = pos[:, 0]  # Y坐标
        zs = pos[:, 1]  # Z坐标

        # 绘制阵元
        ax.scatter(xs, ys, zs, s=80, c="#1d4ed8", marker="o", zorder=5, label="阵元")

        # 标注编号
        for i, (x, y, z) in enumerate(zip(xs, ys, zs)):
            ax.text(x, y, z, f"  {i+1}", fontsize=8, fontweight="bold", color="#1d4ed8")

        # 绘制阵面（矩形的Y-Z平面示意）
        y_margin = max(np.ptp(ys), 0.05) * 0.15
        z_margin = max(np.ptp(zs), 0.05) * 0.15
        y_center = ys.mean()
        z_center = zs.mean()

        # 绘制阵面半透明矩形（必须用 numpy 数组）
        y_span = max(np.ptp(ys), 0.05) + y_margin
        z_span = max(np.ptp(zs), 0.05) + z_margin
        xx = np.array([[0, 0], [0, 0]])
        yy = np.array(
            [
                [y_center - y_span / 2, y_center + y_span / 2],
                [y_center - y_span / 2, y_center + y_span / 2],
            ]
        )
        zz = np.array(
            [
                [z_center - z_span / 2, z_center - z_span / 2],
                [z_center + z_span / 2, z_center + z_span / 2],
            ]
        )
        ax.plot_surface(xx, yy, zz, alpha=0.06, color="#6366f1")

        # 绘制每个目标的来波方向箭头（从阵面中心沿X方向出射）
        try:
            targets = self.get_targets()
        except Exception:
            targets = [{"theta": 30, "phi": 0}]
        arrow_len = max(y_span, z_span, 0.1) * 0.6
        target_colors = ["#ef4444", "#f59e0b", "#10b981", "#8b5cf6", "#ec4899", "#14b8a6"]
        for idx, target in enumerate(targets):
            theta = target["theta"]
            phi = target["phi"]
            color = target_colors[idx % len(target_colors)]
            dir_x = np.cos(np.deg2rad(phi)) * np.cos(np.deg2rad(theta))
            dir_y = np.cos(np.deg2rad(phi)) * np.sin(np.deg2rad(theta))
            dir_z = np.sin(np.deg2rad(phi))
            ax.quiver(
                0,
                y_center,
                z_center,
                dir_x * arrow_len,
                dir_y * arrow_len,
                dir_z * arrow_len,
                color=color,
                linewidth=2.2,
                arrow_length_ratio=0.15,
                label=f"目标{idx + 1} θ={theta}°, φ={phi}°",
            )

        # 坐标轴标注
        ax.set_xlabel("X (法线)", fontsize=10, labelpad=8)
        ax.set_ylabel("Y (右)", fontsize=10, labelpad=8)
        ax.set_zlabel("Z (上)", fontsize=10, labelpad=8)
        ax.set_title("阵列布局 (3D) - 右手坐标系", fontsize=11, fontweight="bold")

        # 设置坐标范围
        max_span = max(y_span, z_span, 0.15)
        ax.set_xlim(-max_span * 0.2, max_span * 1.0)
        ax.set_ylim(y_center - max_span / 1.5, y_center + max_span / 1.5)
        ax.set_zlim(z_center - max_span / 1.5, z_center + max_span / 1.5)

        # 设置视角（从右前上方看）
        ax.view_init(elev=25, azim=-60)

        ax.legend(fontsize=8, loc="upper right")

        fig.tight_layout()
        self.array_canvas.draw()

    def _plot_spectrum(self, P, thetas, theta_ests, targets):
        """绘制空间谱图"""
        fig = self.spectrum_figure
        fig.clear()
        ax = fig.add_subplot(111)

        # 转为dB
        P_db = 10 * np.log10(np.maximum(P, 1e-30))
        ax.plot(thetas, P_db, color="#1d4ed8", linewidth=2.0, label="空间谱")

        for idx, target in enumerate(targets):
            theta_true = target["theta"]
            label = f"真实{idx + 1}: {theta_true}°" if idx == 0 else f"真实{idx + 1}: {theta_true}°"
            ax.axvline(
                theta_true, color="#10b981", linestyle="--", linewidth=1.5, alpha=0.8, label=label
            )

        for idx, theta_est in enumerate(theta_ests):
            ax.axvline(
                theta_est,
                color="#ef4444",
                linestyle=":",
                linewidth=1.6,
                alpha=0.9,
                label=f"估计{idx + 1}: {theta_est:.2f}°",
            )

        ax.set_xlabel("角度 (°)")
        ax.set_ylabel("功率 (dB)")
        ax.set_title("DOA估计空间谱", fontsize=12, fontweight="bold")
        ax.grid(True, linestyle="--", alpha=0.3)
        ax.legend(fontsize=9)

        fig.tight_layout()
        self.spectrum_canvas.draw()

    def _plot_mc_results(self, errors, theta_true, errors_phi=None, phi_true=None):
        """绘制蒙特卡洛结果
        支持1D(仅theta)和2D(theta+phi)两种模式
        """
        fig = self.mc_figure
        fig.clear()

        if len(errors) == 0:
            self.mc_canvas.draw()
            return

        if errors_phi is not None:
            # 2D模式: 4个子图 (theta直方图, theta散点, phi直方图, phi散点)
            ax1 = fig.add_subplot(221)
            n, bins, patches = ax1.hist(
                errors, bins="auto", density=True, alpha=0.7, color="#6366f1", edgecolor="white"
            )
            ax1.axvline(0, color="#10b981", linestyle="--", linewidth=1.5, label="无偏")
            ax1.set_xlabel("θ误差 (°)")
            ax1.set_ylabel("概率密度")
            ax1.set_title("方位角误差分布", fontsize=11, fontweight="bold")
            ax1.grid(True, linestyle="--", alpha=0.3)
            ax1.legend(fontsize=8)

            ax2 = fig.add_subplot(222)
            ax2.scatter(range(len(errors)), errors, s=8, alpha=0.5, color="#6366f1")
            ax2.axhline(0, color="#10b981", linestyle="--", linewidth=1.0)
            ax2.set_xlabel("试验次数")
            ax2.set_ylabel("θ误差 (°)")
            ax2.set_title("方位角各次试验误差", fontsize=11, fontweight="bold")
            ax2.grid(True, linestyle="--", alpha=0.3)

            ax3 = fig.add_subplot(223)
            n_p, bins_p, patches_p = ax3.hist(
                errors_phi, bins="auto", density=True, alpha=0.7, color="#f59e0b", edgecolor="white"
            )
            ax3.axvline(0, color="#10b981", linestyle="--", linewidth=1.5, label="无偏")
            ax3.set_xlabel("φ误差 (°)")
            ax3.set_ylabel("概率密度")
            ax3.set_title("俯仰角误差分布", fontsize=11, fontweight="bold")
            ax3.grid(True, linestyle="--", alpha=0.3)
            ax3.legend(fontsize=8)

            ax4 = fig.add_subplot(224)
            ax4.scatter(range(len(errors_phi)), errors_phi, s=8, alpha=0.5, color="#f59e0b")
            ax4.axhline(0, color="#10b981", linestyle="--", linewidth=1.0)
            ax4.set_xlabel("试验次数")
            ax4.set_ylabel("φ误差 (°)")
            ax4.set_title("俯仰角各次试验误差", fontsize=11, fontweight="bold")
            ax4.grid(True, linestyle="--", alpha=0.3)
        else:
            # 1D模式: 2个子图 (保持不变)
            ax1 = fig.add_subplot(121)
            n, bins, patches = ax1.hist(
                errors, bins="auto", density=True, alpha=0.7, color="#6366f1", edgecolor="white"
            )
            ax1.axvline(0, color="#10b981", linestyle="--", linewidth=1.5, label="无偏")
            ax1.set_xlabel("误差 (°)")
            ax1.set_ylabel("概率密度")
            ax1.set_title("误差分布直方图", fontsize=11, fontweight="bold")
            ax1.grid(True, linestyle="--", alpha=0.3)
            ax1.legend(fontsize=8)

            ax2 = fig.add_subplot(122)
            ax2.scatter(range(len(errors)), errors, s=8, alpha=0.5, color="#6366f1")
            ax2.axhline(0, color="#10b981", linestyle="--", linewidth=1.0)
            ax2.set_xlabel("试验次数")
            ax2.set_ylabel("误差 (°)")
            ax2.set_title("各次试验误差", fontsize=11, fontweight="bold")
            ax2.grid(True, linestyle="--", alpha=0.3)

        fig.tight_layout()
        self.mc_canvas.draw()

    def _plot_spectrum_2d(self, P, thetas, phis, theta_ests, phi_ests, targets):
        """绘制二维空间谱热力图"""
        fig = self.spectrum_figure
        fig.clear()
        ax = fig.add_subplot(111)

        P_db = 10 * np.log10(np.maximum(P, 1e-30))
        im = ax.imshow(
            P_db,
            aspect="auto",
            origin="lower",
            extent=[thetas[0], thetas[-1], phis[0], phis[-1]],
            cmap="jet",
        )
        fig.colorbar(im, ax=ax, label="功率 (dB)")
        for idx, target in enumerate(targets):
            ax.plot(
                target["theta"],
                target["phi"],
                "g*",
                markersize=13,
                label=f"真实{idx + 1} θ={target['theta']}°, φ={target['phi']}°",
            )
        for idx, (theta_est, phi_est) in enumerate(zip(theta_ests, phi_ests)):
            ax.plot(
                theta_est,
                phi_est,
                "rx",
                markersize=11,
                markeredgewidth=2.5,
                label=f"估计{idx + 1} θ={theta_est:.2f}°, φ={phi_est:.2f}°",
            )
        ax.set_xlabel("方位角 (°)")
        ax.set_ylabel("俯仰角 (°)")
        ax.set_title("二维DOA估计空间谱", fontsize=12, fontweight="bold")
        ax.legend(fontsize=9)

        fig.tight_layout()
        self.spectrum_canvas.draw()
