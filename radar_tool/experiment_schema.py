"""Experiment record schema validation and normalization."""
import copy

from . import exp_recorder as _context
from .experiment_images import _normalize_image_reference
from .schemas import ProjectRecord, migrate_schema

def validate_experiment_id(value, field_name='ID'):
    """Validate identifiers used as path and JSON mapping keys."""
    if not isinstance(value, str) or not _context.EXPERIMENT_ID_PATTERN.fullmatch(value):
        raise ValueError(f'{field_name} 只能包含字母、数字、下划线或连字符')
    return value
def _normalize_text_fields(record, fields):
    for field in fields:
        if field in record and not isinstance(record[field], str):
            raise ValueError(f'记录字段 {field} 必须是字符串')
def _normalize_record(record):
    if not isinstance(record, dict):
        raise ValueError('记录必须是 JSON 对象')
    _normalize_text_fields(
        record,
        (
            'title', 'date', 'personnel', 'location', 'template',
            'conditions', 'content', 'conclusion', 'data', 'created', 'updated',
        ),
    )
    if 'steps' in record and not isinstance(record['steps'], list):
        raise ValueError('记录 steps 必须是数组')
    for step in record.get('steps', []):
        if not isinstance(step, dict):
            raise ValueError('试验步骤必须是 JSON 对象')
        _normalize_text_fields(step, ('title', 'desc', 'data'))
        if 'images' in step and not isinstance(step['images'], list):
            raise ValueError('步骤 images 必须是数组')
        if 'images' in step:
            step['images'] = [
                _normalize_image_reference(image) for image in step['images']
            ]
    if 'images' in record:
        if not isinstance(record['images'], list):
            raise ValueError('记录 images 必须是数组')
        record['images'] = [_normalize_image_reference(image) for image in record['images']]
    return record
def _normalize_projects_payload(payload):
    document = migrate_schema(payload, 'project_record')
    if set(document) != _context.EXPERIMENTS_SCHEMA_KEYS:
        raise ValueError('试验数据 Schema 字段不完整')
    projects = document.get('projects')
    if not isinstance(projects, dict):
        raise ValueError('projects 必须是 JSON 对象')
    normalized = copy.deepcopy(projects)
    for project_id, project in normalized.items():
        validate_experiment_id(project_id, '项目 ID')
        if not isinstance(project, dict):
            raise ValueError('项目必须是 JSON 对象')
        ProjectRecord.from_dict(project_id, project)
        if 'name' in project and not isinstance(project['name'], str):
            raise ValueError('项目 name 必须是字符串')
        if 'description' in project and not isinstance(project['description'], str):
            raise ValueError('项目 description 必须是字符串')
        if 'tasks' in project and not isinstance(project['tasks'], dict):
            raise ValueError('项目 tasks 必须是 JSON 对象')
        tasks = project.get('tasks', {})
        for task_id, task in tasks.items():
            validate_experiment_id(task_id, '任务 ID')
            if not isinstance(task, dict):
                raise ValueError('任务必须是 JSON 对象')
            if 'name' in task and not isinstance(task['name'], str):
                raise ValueError('任务 name 必须是字符串')
            if 'records' in task and not isinstance(task['records'], dict):
                raise ValueError('任务 records 必须是 JSON 对象')
            records = task.get('records', {})
            for record_id, record in records.items():
                validate_experiment_id(record_id, '记录 ID')
                _normalize_record(record)
    return normalized
