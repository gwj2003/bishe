import os
# 引入 PromptTemplate
from langchain_core.prompts import PromptTemplate
from langchain_community.chains.graph_qa.cypher import GraphCypherQAChain
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI

# ================= 1. 配置区域 =================
os.environ["OPENAI_API_KEY"] = "sk-5e6dd505dfba4033bdfd652f00c30959"
os.environ["OPENAI_API_BASE"] = "https://api.deepseek.com"

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "12345sss"

# ================= 2. 初始化核心组件 =================

graph = Neo4jGraph(
    url=NEO4J_URI,
    username=NEO4J_USERNAME,
    password=NEO4J_PASSWORD,
    refresh_schema=False
)

# 【关键修改】这里必须根据你刚才导入的数据结构来写！
# 否则 AI 只能看到 "Entity" 节点，查不到 "Taxonomy" 或 "Location"
graph.structured_schema = {
    "node_props": {
        "Species": [{"property": "name", "type": "STRING"}],
        "Taxonomy": [{"property": "name", "type": "STRING"}],
        "Location": [{"property": "name", "type": "STRING"}],
        "Impact": [{"property": "name", "type": "STRING"}],
        "Control": [{"property": "name", "type": "STRING"}]
    },
    "relationships": [
        {"start": "Species", "type": "HAS_ALIAS", "end": "Species"},
        {"start": "Species", "type": "BELONGS_TO", "end": "Taxonomy"},
        {"start": "Species", "type": "NATIVE_TO", "end": "Location"},
        {"start": "Species", "type": "INVADES", "end": "Location"},
        {"start": "Species", "type": "CAUSES", "end": "Impact"},
        {"start": "Species", "type": "SUPPRESSED_BY", "end": "Control"}
    ],
    "metadata": {}
}

llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0,
    max_tokens=1024
)

# ================= 3. 提示词工程 (全中文版) =================

# 1. 生成 Cypher 语句的中文提示词
CYPHER_GENERATION_TEMPLATE = """
任务：你是一个 Neo4j 图数据库专家。请根据用户的问题，将其转换为 Cypher 查询语句。

Schema（数据库结构）：
{schema}

说明与约束：
1. 仅使用 Schema 中提供的节点标签（如 Species, Location等）和关系类型（如 INVADES, CAUSES等）。
2. 不要编造不存在的关系或属性。
3. 查询时只使用 MATCH 语句，严禁使用 CREATE 或 DELETE 等修改数据的语句。
4. 在查询 `name` 属性时，请使用 `CONTAINS` 进行模糊匹配，以提高命中率（例如：WHERE n.name CONTAINS '福寿螺'）。
5. 必须考虑关系的属性：
   - 如果用户问“什么时候入侵的”，请返回 INVADES 关系的 `time` 属性。
   - 如果用户问“属于什么科”，请查询 BELONGS_TO 关系指向的 Taxonomy 节点。
   - 如果用户问“有什么危害”，请查询 CAUSES 关系指向的 Impact 节点。
6. 只输出 Cypher 语句字符串，不要包含 markdown 标记（如 ```cypher）或任何解释性文字。

用户问题：{question}

Cypher 查询语句："""

CYPHER_PROMPT = PromptTemplate(
    input_variables=["schema", "question"],
    template=CYPHER_GENERATION_TEMPLATE
)

# 2. 生成最终回答的中文提示词
QA_TEMPLATE = """
你是一个生物入侵领域的智能助手。请根据以下从数据库查到的“上下文”信息回答用户问题。

上下文信息：
{context}

用户问题：
{question}

回答要求：
1. **完全基于上下文**：请直接根据上面的上下文信息回答，不要编造。
2. **处理空结果**：如果上下文是空的（[]），请委婉地回答：“数据库中暂时没有关于该问题的记录。”
3. **语言风格**：请使用中文，回答简洁、专业、条理清晰。
4. **整合信息**：如果有多条记录（例如多个别名或多种危害），请用自然语言将它们串联起来。

你的回答："""

QA_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=QA_TEMPLATE
)

# ================= 4. 构建 Chain =================

chain = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    verbose=True,
    validate_cypher=True,
    top_k=10,
    allow_dangerous_requests=True,
    cypher_prompt=CYPHER_PROMPT,
    qa_prompt=QA_PROMPT
)

# ================= 5. 测试函数 =================

def ask_bot(question):
    print(f"\n{'=' * 40}")
    print(f"🙋 提问: {question}")
    try:
        response = chain.invoke({"query": question})
        # 这里的 key 在不同版本可能是 'result' 或 'output'
        # print(f"🔍 生成的 Cypher: {response.get('generated_cypher')}")
        print(f"🤖 AI 回答: {response.get('result')}")
    except Exception as e:
        print(f"❌ 出错: {e}")

if __name__ == "__main__":
    print("✅ Neo4j 连接成功 (Schema 已根据导入数据更新)")

    # 测试问题
    ask_bot("福寿螺有什么别名？")
    ask_bot("福寿螺属于哪个科？")       # 测试 Taxonomy
    ask_bot("福寿螺会对农业造成什么危害？") # 测试 Impact
    ask_bot("怎么防治福寿螺？")         # 测试 Control
    ask_bot("福寿螺和鳄雀鳝有什么异同？")