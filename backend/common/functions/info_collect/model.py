"""信息收集数据模型 - 学生信息字段定义和验证"""
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from pydantic import BaseModel


# 学生信息字段元数据（用于表单填写和信息提取）
STUDENT_FIELDS_META = {
    "real_name": {
        "label": "姓名",
        "type": "text",
        "required": True,
        "placeholder": "请输入您的姓名",
    },
    "age": {
        "label": "年龄",
        "type": "integer",
        "required": True,
        "min": 16,
        "max": 60,
        "placeholder": "请输入您的年龄",
    },
    "gender": {
        "label": "性别",
        "type": "enum",
        "required": False,
        "options": ["男", "女"],
        "placeholder": "请选择性别",
    },
    "phone": {
        "label": "手机号",
        "type": "phone",
        "required": False,
        "placeholder": "请输入您的手机号",
    },
    "wechat": {
        "label": "微信",
        "type": "text",
        "required": False,
        "placeholder": "请输入您的微信号",
    },
    "target_country": {
        "label": "目标国家",
        "type": "enum",
        "required": True,
        "options": ["美国", "英国", "加拿大", "澳洲", "香港", "新加坡", "其他"],
        "placeholder": "请选择目标留学国家",
    },
    "target_level": {
        "label": "目标学位",
        "type": "enum",
        "required": True,
        "options": ["本科", "硕士", "博士"],
        "placeholder": "请选择目标学位",
    },
    "target_major": {
        "label": "目标专业",
        "type": "text",
        "required": True,
        "placeholder": "请输入您的目标专业",
    },
    "current_school": {
        "label": "当前学校",
        "type": "text",
        "required": False,
        "placeholder": "请输入您当前就读的学校",
    },
    "current_major": {
        "label": "当前专业",
        "type": "text",
        "required": False,
        "placeholder": "请输入您当前的专业",
    },
    "gpa": {
        "label": "GPA",
        "type": "float",
        "required": False,
        "min": 0.0,
        "max": 4.0,
        "placeholder": "请输入您的GPA（0.0-4.0）",
    },
    "language_type": {
        "label": "语言考试类型",
        "type": "enum",
        "required": False,
        "options": ["雅思", "托福", "PTE", "多邻国", "暂无"],
        "placeholder": "请选择语言考试类型",
    },
    "language_score": {
        "label": "语言成绩",
        "type": "float",
        "required": False,
        "min": 0.0,
        "max": 9.0,
        "placeholder": "请输入您的语言成绩",
    },
    "budget": {
        "label": "预算",
        "type": "enum",
        "required": False,
        "options": ["30万以下", "30-50万", "50-80万", "80万以上", "不限"],
        "placeholder": "请选择您的留学预算",
    },
    "entry_time": {
        "label": "入学时间",
        "type": "enum",
        "required": False,
        "options": ["2024年", "2025年", "2026年", "未确定"],
        "placeholder": "请选择计划入学时间",
    },
    "gpa_system": {
        "label": "GPA制度",
        "type": "enum",
        "required": False,
        "options": ["4.0制", "5.0制", "100分制"],
        "placeholder": "请选择GPA计算制度",
    },
    "current_grade": {
        "label": "当前年级",
        "type": "enum",
        "required": False,
        "options": ["大一", "大二", "大三", "大四", "已毕业", "高中"],
        "placeholder": "请选择您的当前年级",
    },
    "internship": {
        "label": "是否有实习经历",
        "type": "enum",
        "required": False,
        "options": ["是", "否"],
        "placeholder": "请选择是否有实习经历",
    },
    "internship_duration": {
        "label": "实习时长",
        "type": "text",
        "required": False,
        "placeholder": "请输入实习时长（如：3个月）",
    },
    "work_experience": {
        "label": "是否有工作经验",
        "type": "enum",
        "required": False,
        "options": ["是", "否"],
        "placeholder": "请选择是否有工作经验",
    },
    "work_years": {
        "label": "工作年限",
        "type": "text",
        "required": False,
        "placeholder": "请输入工作年限",
    },
    "notes": {
        "label": "备注",
        "type": "textarea",
        "required": False,
        "placeholder": "其他需要说明的情况",
    },
}


def validate_and_convert_field(field_name: str, value: Any) -> Tuple[Any, Optional[str]]:
    """验证并转换字段值
    
    Args:
        field_name: 字段名
        value: 字段值
        
    Returns:
        Tuple[Any, Optional[str]]: (转换后的值, 错误信息)
    """
    meta = STUDENT_FIELDS_META.get(field_name)
    if not meta:
        return value, f"未知字段: {field_name}"
    
    field_type = meta.get("type")
    
    try:
        # 文本类型
        if field_type == "text":
            return str(value).strip(), None
        
        # 整数类型
        elif field_type == "integer":
            val = int(float(value))
            min_val = meta.get("min")
            max_val = meta.get("max")
            if min_val and val < min_val:
                return None, f"{meta['label']}不能小于{min_val}"
            if max_val and val > max_val:
                return None, f"{meta['label']}不能大于{max_val}"
            return val, None
        
        # 浮点数类型
        elif field_type == "float":
            val = float(value)
            min_val = meta.get("min")
            max_val = meta.get("max")
            if min_val and val < min_val:
                return None, f"{meta['label']}不能小于{min_val}"
            if max_val and val > max_val:
                return None, f"{meta['label']}不能大于{max_val}"
            return val, None
        
        # 枚举类型
        elif field_type == "enum":
            options = meta.get("options", [])
            val_str = str(value).strip()
            # 尝试匹配
            for opt in options:
                if val_str == opt or val_str in opt:
                    return opt, None
            return None, f"{meta['label']}必须是以下选项之一: {', '.join(options)}"
        
        # 电话类型
        elif field_type == "phone":
            val = str(value).strip()
            if not val.isdigit() or len(val) != 11:
                return None, "请输入有效的11位手机号"
            return val, None
        
        # 文本域类型
        elif field_type == "textarea":
            return str(value).strip(), None
        
        else:
            return value, None
            
    except Exception as e:
        return None, f"{meta['label']}格式错误: {str(e)}"


def get_field_schema_text() -> str:
    """获取字段schema文本（用于LLM prompt）
    
    Returns:
        str: 字段schema描述
    """
    lines = []
    for field_name, meta in STUDENT_FIELDS_META.items():
        field_type = meta.get("type")
        label = meta.get("label")
        required = meta.get("required", False)
        
        line = f"- {field_name} ({label})"
        if required:
            line += " [必填]"
        
        if field_type == "enum":
            options = meta.get("options", [])
            line += f" 枚举值: {', '.join(options)}"
        elif field_type in ["integer", "float"]:
            min_val = meta.get("min")
            max_val = meta.get("max")
            if min_val or max_val:
                line += f" 范围: {min_val or '不限'}-{max_val or '不限'}"
        
        lines.append(line)
    
    return "\n".join(lines)


def get_missing_fields(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """获取缺失的字段列表
    
    Args:
        profile: 用户profile
        
    Returns:
        List[Dict]: 缺失字段的元数据列表
    """
    missing = []
    for field_name, meta in STUDENT_FIELDS_META.items():
        if meta.get("required", False):
            val = profile.get(field_name)
            if val is None or str(val).strip() == "":
                missing.append({
                    "field": field_name,
                    **meta
                })
    return missing


@dataclass
class ExtractionResult:
    """信息提取结果"""
    success: bool
    updated_fields: List[str]
    snapshot: Dict[str, Any]
    failed_fields: List[str]
    suggested_feedback: str


@dataclass
class RagContext:
    """RAG检索上下文"""
    retrieved_chunks: List[str]
    query_summary: str


@dataclass
class NotesSummaryResult:
    """备注总结结果"""
    success: bool
    changed: bool
    updated_notes: str
    extracted_keywords: List[str]


@dataclass
class SummaryContext:
    """汇总上下文"""
    extraction: Optional[ExtractionResult] = None
    rag: Optional[RagContext] = None
    notes: Optional[NotesSummaryResult] = None
    intents: List[str] = None
