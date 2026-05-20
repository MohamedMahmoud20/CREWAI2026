from crewai import Agent, Crew, Task
from myproject.config.llm_config import local_llm


def test_ollama_crewai_connection():
    agent = Agent(
        role="Ollama Test Agent",
        goal="Verify Ollama is used as the LLM provider",
        backstory="""
        This agent only checks that the configured LLM provider is Ollama and can respond.
        """,
        llm=local_llm,
        verbose=False,
    )

    task = Task(
        description="The user request is: {user_request}",
        agent=agent,
        expected_output="A simple confirmation that Ollama is connected.",
    )

    crew = Crew(agents=[agent], tasks=[task])
    result = crew.kickoff(
        inputs={
            "user_request": "تحقق من الاتصال مع موديل Gemma عبر Ollama.",
        }
    )

    assert result is not None
    assert len(str(result).strip()) > 0
    assert local_llm.model == "ollama/gemma3:1b"

    print(
        "الآن CrewAI يستخدم موديل Gemma من خادم Ollama الخاص بك: "
        f"{local_llm.model} @ {local_llm.base_url}"
    )
