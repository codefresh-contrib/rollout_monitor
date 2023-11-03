# Rollout Monitor

Step to monitor a Rollout in a Codefresh's GitOps Runtime

## Development

-   To activate venv

```sh
python3 -m venv venv --clear
source venv/bin/activate
```

-   Download all dependencies

```sh
pip install --upgrade pip
pip install -r requirements.txt
```

-   Update list of requirements:

```sh
pip freeze > requirements.txt
```

## Running it

Create a variables.env file with the following content:

```sh
CF_API_KEY=XYZ
RUNTIME=<the_runtime_name>
APPLICATION=<the_app_name>
ROLLOUT=<the_rollout_name>
COMMIT_SHA=<the_commit_sha_of_the_release>
```

-   Running in shell:

```sh
export $( cat variables.env | xargs ) && python -u monitor_rollout.py
```

-   Running as a container:

```sh
export image_name="`yq .name service.yaml`"
export image_tag="`yq .version service.yaml`"
export registry="franciscocodefresh" ## Docker Hub
docker build -t ${image_name} .
docker run --rm --env-file variables.env ${image_name}
```

-   Pushing the image:

```sh
docker tag ${image_name} ${registry}/${image_name}:${image_tag}
docker push ${registry}/${image_name}:${image_tag}
```
