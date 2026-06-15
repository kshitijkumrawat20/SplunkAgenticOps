import os
import sys
import json
import logging
from typing import Dict, Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("opspilot.mcp_client")

class SplunkMCPClient:
    """
    SplunkMCPClient implements a reusable layer that communicates with the Splunk MCP Server
    using the official Model Context Protocol (MCP) Python SDK via the mcp-remote bridge.
    """
    def __init__(self, token: Optional[str] = None):
        self.token = token or self._load_token()
        if not self.token:
            logger.error("Splunk MCP Token not found in environment or .env file.")
            raise ValueError("Splunk MCP Token not found")
        
        # Configure env variables for the subprocess to bypass SSL self-signed certificates
        self.server_env = os.environ.copy()
        self.server_env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
        
        self._read_stream = None
        self._write_stream = None
        self._session = None
        self._client_ctx = None

    def _load_token(self) -> Optional[str]:
        # Try environment variable
        token = os.getenv("MCP_Encrypted_Token")
        if token:
            return token
            
        # Try reading .env file
        env_paths = [".env", "../.env", "../../.env"]
        for path in env_paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.strip().startswith("MCP_Encrypted_Token="):
                            return line.strip().split("=", 1)[1]
        return None

    async def connect(self):
        """Initializes the stdio client connection to mcp-remote."""
        logger.info("Connecting to Splunk MCP Server via mcp-remote...")
        # On Windows, we use npx.cmd; on other systems, we use npx.
        command = "npx.cmd" if sys.platform == "win32" else "npx"
        
        server_params = StdioServerParameters(
            command=command,
            args=[
                "-y",
                "mcp-remote",
                "https://localhost:8089/services/mcp",
                "--header",
                f"Authorization: Bearer {self.token}"
            ],
            env=self.server_env
        )
        
        try:
            self._client_ctx = stdio_client(server_params)
            self._read_stream, self._write_stream = await self._client_ctx.__aenter__()
            self._session = ClientSession(self._read_stream, self._write_stream)
            await self._session.__aenter__()
            await self._session.initialize()
            logger.info("Successfully connected and initialized Splunk MCP Session.")
        except Exception as e:
            logger.error(f"Failed to connect to Splunk MCP Server: {e}")
            await self.disconnect()
            raise

    async def disconnect(self):
        """Closes session and subprocess connections."""
        logger.info("Disconnecting Splunk MCP Client...")
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
            
        if self._client_ctx:
            try:
                await self._client_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._client_ctx = None
            
        self._read_stream = None
        self._write_stream = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def search_logs(self, query: str, earliest_time: str = "-24h", latest_time: str = "now", row_limit: int = 100) -> Dict[str, Any]:
        """
        Executes a search query using search_logs (mapped to splunk_run_query).
        """
        if not self._session:
            raise RuntimeError("Client is not connected. Use 'async with' context manager.")
            
        logger.info(f"Executing search_logs SPL query: {query}")
        try:
            res = await self._session.call_tool("splunk_run_query", {
                "query": query,
                "earliest_time": earliest_time,
                "latest_time": latest_time,
                "row_limit": row_limit
            })
            
            if not res.content or len(res.content) == 0:
                return {"results": []}
                
            text_data = res.content[0].text
            return json.loads(text_data)
        except Exception as e:
            logger.error(f"Error executing search_logs: {e}")
            return {"results": [], "error": str(e)}

    async def get_alerts(self) -> Dict[str, Any]:
        """
        Retrieves active alerts (mapped to splunk_get_knowledge_objects for alerts).
        """
        if not self._session:
            raise RuntimeError("Client is not connected. Use 'async with' context manager.")
            
        logger.info("Retrieving alerts from Splunk MCP...")
        try:
            res = await self._session.call_tool("splunk_get_knowledge_objects", {
                "type": "alerts"
            })
            
            if not res.content or len(res.content) == 0:
                return {"results": []}
                
            text_data = res.content[0].text
            return json.loads(text_data)
        except Exception as e:
            logger.error(f"Error retrieving alerts: {e}")
            return {"results": [], "error": str(e)}

    async def search_events(self, query: str, earliest_time: str = "-24h", latest_time: str = "now", row_limit: int = 100) -> Dict[str, Any]:
        """
        Performs event search (mapped to splunk_run_query).
        """
        # Under the hood, this is identical to search_logs since they both run searches.
        return await self.search_logs(query, earliest_time, latest_time, row_limit)
