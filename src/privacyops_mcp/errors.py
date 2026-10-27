"""One error shape for every module, so scripts can rely on it.

Every failure a tool reports reads: ``privacyops.<module>.<code>: <message> Fix: <hint>``.
"""

from mcp.server.fastmcp.exceptions import ToolError


class PrivacyOpsError(ToolError):
    def __init__(self, module: str, code: str, message: str, hint: str = ""):
        self.module = module
        self.code = code
        text = f"privacyops.{module}.{code}: {message}"
        if hint:
            text += f" Fix: {hint}"
        super().__init__(text)
