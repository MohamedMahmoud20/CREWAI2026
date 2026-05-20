# crew_setup.py — Crew بسيطة: Agent واحد + Task واحدة
from crewai import Crew, Process

from myproject.config.agents import client_agent
from myproject.config.tasks import client_task

client_crew = Crew(
    agents=[client_agent],
    tasks=[client_task],
    process=Process.sequential,
    verbose=False,
)
