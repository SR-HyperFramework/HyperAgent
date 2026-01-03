import asyncio
import os
from contextlib import AsyncExitStack
from typing import Optional, Any, Dict, List

# Importing from mcp library - assuming standard SDK usage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPClientManager:
    def __init__(self, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        self.command = command
        self.args = args
        self.env = env if env else os.environ.copy()
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()

    async def connect(self):
        """Establishes connection to the MCP server via Stdio."""
        if self.session:
            return

        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env
        )

        try:
            # Enter the stdio_client context
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            self.session = await self.exit_stack.enter_async_context(ClientSession(stdio_transport[0], stdio_transport[1]))
            await self.session.initialize()
            print("MCP Client Connected!")
        except Exception as e:
            print(f"Failed to connect to MCP Server: {e}")
            raise

    async def list_tools(self):
        """Lists available tools from the server."""
        if not self.session:
            raise RuntimeError("Client not connected")
        return await self.session.list_tools()

    async def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        """Calls a tool on the MCP server."""
        if not self.session:
            raise RuntimeError("Client not connected")
        
        result = await self.session.call_tool(name, arguments=arguments or {})
        return result

    async def close(self):
        """Closes the connection."""
        await self.exit_stack.aclose()
        self.session = None

# Example functionality wrapper particularly for IDA
class IDAMCPClient(MCPClientManager):
    def __init__(self, file_path: str, host: str = "127.0.0.1", port: int = 8745):
        # We invoke the server process. The prompt suggested:
        # uv run idalib-mcp --host ... --port ... <file>
        # Note: 'uv' might be a separate tool management command.
        
        # NOTE: logic to locate 'uv' or 'idalib-mcp' should be robust.
        # For now, following prompt literally.
        cmd = "uv"
        args = ["run", "idalib-mcp", "--host", host, "--port", str(port), file_path]
        
        super().__init__(command=cmd, args=args)
    
    async def get_decompilation(self, address: str) -> str:
        # Wrapper for a specific tool 'get_decompilation'
        res = await self.call_tool("get_decompilation", {"address": address})
        # Parse result (usually content is in res.content[0].text)
        return res

if __name__ == "__main__":
    # Test stub
    async def main():
        # This requires actual 'uv' and 'idalib-mcp' installed to work
        pass

    # asyncio.run(main())
