from src.core.agent import ReActAgent
from src.core.framework import AgentConfig

def test():
    config = AgentConfig()
    agent = ReActAgent(config=config)
    agent.tool_registry.register_default_external_tools()
    
    print("Agent is running...")
    response = agent.run("What is 15 * 42?")
    print("Response:", response)

if __name__ == "__main__":
    test()
