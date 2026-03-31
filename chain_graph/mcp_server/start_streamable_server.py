from chain_graph.mcp_server.tool_server2 import server

if __name__ == '__main__':
    server.run(
        transport='streamable-http',
        host='127.0.0.1',
        show_banner=True,
        port=8080,
        log_level='debug',
        path='/streamable'
    )
