# @Author: RebeccaZhou
# @Description: Entity type enums (aligned with graph schema)
#              实体类型枚举（与图谱 Schema 对齐）。
from enum import Enum

class EntityType(str, Enum):
    Model = "Model"
    Filter = "Filter"
    Fault = "Fault"
    Cause = "Cause"
    Solution = "Solution"
    Customer = "Customer"
    Order = "Order"
    Batch = "Batch"

class Intent(str, Enum):
    filter_compatibility = "filter_compatibility"
    fault_diagnosis = "fault_diagnosis"
    batch_recall = "batch_recall"
    general = "general"
