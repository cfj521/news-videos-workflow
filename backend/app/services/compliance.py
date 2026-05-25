from dataclasses import dataclass, field

DEFAULT_SENSITIVE_KEYWORDS = [
    "暴力",
    "恐怖",
    "赌博",
    "色情",
    "毒品",
    "枪支",
    "爆炸物",
    "自杀",
    "自残",
]


@dataclass
class ComplianceResult:
    status: str  # passed | blocked | review
    matched_keywords: list[str] = field(default_factory=list)
    reason: str = ""


class ComplianceService:
    def __init__(self, sensitive_keywords: list[str] | None = None):
        self.sensitive_keywords = (
            sensitive_keywords if sensitive_keywords is not None else DEFAULT_SENSITIVE_KEYWORDS
        )

    def check(self, content: str, title: str = "") -> ComplianceResult:
        combined = f"{title} {content}".lower()
        matched = [kw for kw in self.sensitive_keywords if kw in combined]

        if matched:
            return ComplianceResult(
                status="blocked",
                matched_keywords=matched,
                reason=f"命中敏感词: {', '.join(matched)}",
            )

        return ComplianceResult(status="passed")
