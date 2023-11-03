FROM    python:3.11.2-slim-buster
WORKDIR /app
COPY    requirements.txt requirements.txt
RUN     pip3 install -r requirements.txt
COPY    queries queries/
COPY    monitor_rollout.py run.py

CMD     [ "python3","-u","run.py"]