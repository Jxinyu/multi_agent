# graph_db.py
import logging
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

from config import settings

# 增加这一行，设置日志级别为 INFO，并简单配置输出格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class EnterpriseGraphStore:
    def __init__(self):
        self.url = settings.neo4j.url
        self.username = settings.neo4j.username
        self.password = settings.neo4j.password

    def get_graph_store(self) -> Neo4jPropertyGraphStore:
        try:
            graph_store = Neo4jPropertyGraphStore(
                username=self.username,
                password=self.password,
                url=self.url,
            )
            logger.info("✅ 成功连接 Neo4j 图数据库")
            return graph_store
        except Exception as e:
            logger.error(f"❌ 连接 Neo4j 失败: {e}")
            raise


if __name__ == '__main__':
    graph_store = EnterpriseGraphStore()
    graph_store.get_graph_store()
    pass
