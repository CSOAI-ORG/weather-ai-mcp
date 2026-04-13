# Weather AI MCP

> Weather intelligence tools - current conditions, forecasts, historical data, agricultural alerts, severe warnings

Built by **MEOK AI Labs** | [meok.ai](https://meok.ai)

## Features

| Tool | Description |
|------|-------------|
| `get_current_conditions` | See tool docstring for details |
| `get_forecast` | See tool docstring for details |
| `get_historical_weather` | See tool docstring for details |
| `get_agricultural_alerts` | See tool docstring for details |
| `get_severe_weather_warnings` | See tool docstring for details |

## Installation

```bash
pip install mcp
```

## Usage

### As an MCP Server

```bash
python server.py
```

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "weather-ai-mcp": {
      "command": "python",
      "args": ["/path/to/weather-ai-mcp/server.py"]
    }
  }
}
```

## Rate Limits

Free tier includes **30-50 calls per tool per day**. Upgrade at [meok.ai/pricing](https://meok.ai/pricing) for unlimited access.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with FastMCP by MEOK AI Labs
