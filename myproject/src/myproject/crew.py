from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from myproject.config.agents import client_agent
from myproject.config.tasks import client_task 



@CrewBase
class Myproject:
    """Myproject crew"""

    agents_config = None
    tasks_config = None

    @agent
    def client_service_agent(self) -> Agent:
        return client_agent

    @task
    def client_task(self) -> Task:
        return client_task

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[self.client_service_agent()],
            tasks=[self.client_task()],
            process=Process.sequential,
            verbose=True,
            planning=False,
        )