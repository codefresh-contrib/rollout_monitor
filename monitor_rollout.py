from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport
import json
import time  # for the sleep function
import os
import requests

# Parameters
RUNTIME = os.getenv('RUNTIME')
APPLICATION = os.getenv('APPLICATION')
APPLICATION_NAMESPACE = os.getenv('APPLICATION_NAMESPACE', '')
COMMIT_SHA = os.getenv('COMMIT_SHA')
ROLLOUT = os.getenv('ROLLOUT')
RELEASES_TO_RETRIEVE = int(os.getenv('RELEASES_TO_RETRIEVE', '20'))

# Defaults | constants
CF_URL = os.getenv('CF_URL', 'https://g.codefresh.io')
CF_API_KEY = os.getenv('CF_API_KEY')
CF_STEP_NAME = os.getenv('CF_STEP_NAME', 'STEP_NAME')

# Inferred during execution time
CF_ACCOUNT_ID = ""  # It will be infered later, using the CF_API_KEY
RUNTIME_NAMESPACE = ""  # It will be infered later, during execution


################################################################################


def main():
    parameters = {
        "RUNTIME": RUNTIME,
        "APPLICATION": APPLICATION,
        "COMMIT_SHA": COMMIT_SHA,
        "ROLLOUT": ROLLOUT
    }
    print("################################################################################")
    print("Monitoring the following Rollout: ")
    print(json.dumps(parameters, indent=4), "\n")

    fetch_runtime_details()

    if rollout_exists() == False:
        print(f"App, Release or Rollout not found. "
              f"It doesn't exist or it's too old "
              f"(it's not in the last {RELEASES_TO_RETRIEVE} releases of the Application).")
        print("Please check your parameters:")
        print(json.dumps(parameters, indent=4), "\n")
        raise Exception("App, Release or Rollout not found")

    # Generating link to the Apps Dashboard
    CF_OUTPUT_URL_VAR = CF_STEP_NAME + '_CF_OUTPUT_URL'
    link_to_app = get_link_to_apps_dashboard()
    export_variable(CF_OUTPUT_URL_VAR, link_to_app)

    print()
    monitor_rollout()
    print("################################################################################")


################################################################################


def get_query(query_name):
    with open('queries/'+query_name+'.graphql', 'r') as file:
        query_content = file.read()
    return gql(query_content)


def get_runtime():
    transport = RequestsHTTPTransport(
        url=CF_URL + '/2.0/api/graphql',
        headers={'authorization': CF_API_KEY},
        verify=True,
        retries=3,
    )
    client = Client(transport=transport, fetch_schema_from_transport=False)
    query = get_query('getRuntime')  # gets gql query
    variables = {
        "runtime": RUNTIME
    }
    runtime = client.execute(query, variable_values=variables)
    return runtime


def query_application_timeline_list_query():
    transport = RequestsHTTPTransport(
        url=CF_URL + '/2.0/api/graphql',
        headers={'authorization': CF_API_KEY},
        verify=True,
        retries=3,
    )

    client = Client(transport=transport, fetch_schema_from_transport=False)
    query = get_query('application_timeline_list_query')  # gets gql query

    variables = {}
    variables['filters'] = {}
    variables['pagination'] = {}
    variables['filters']['name'] = APPLICATION
    variables['filters']['namespace'] = APPLICATION_NAMESPACE or RUNTIME_NAMESPACE
    variables['filters']['runtime'] = RUNTIME
    variables['pagination']['first'] = RELEASES_TO_RETRIEVE

    result = client.execute(query, variable_values=variables)

    return result


def query_rollout_resource(runtime_ingress_host):
    transport = RequestsHTTPTransport(
        url=runtime_ingress_host + '/app-proxy/api/graphql',
        headers={'authorization': CF_API_KEY},
        verify=True,
        retries=3,
    )

    client = Client(transport=transport, fetch_schema_from_transport=False)
    query = get_query('get_resource')  # gets gql query

    variables = {
        "application": APPLICATION,
        "kind": "Rollout",
        "name": ROLLOUT,
        "resourceName": ROLLOUT,
        "version": "v1alpha1",
        "group": "argoproj.io"
    }

    result = client.execute(query, variable_values=variables)
    return result


def fetch_runtime_details():
    runtime = get_runtime()
    runtime_ns = runtime['runtime']['metadata']['namespace']
    global RUNTIME_NAMESPACE
    RUNTIME_NAMESPACE = str(runtime_ns)


def look_for_release_by_commit(releases, commit_sha):
    release_found = {}
    for release in releases:
        release_commit = release['node']['application']['status']['revision']
        if release_commit == commit_sha:
            release_found = release['node']
    return release_found


def look_for_rollout_by_rollout_name(rollouts, rollout_name):
    rollout_found = {}
    for rollout in rollouts:
        if rollout_name == rollout['to']['name']:
            rollout_found = rollout['to']
    return rollout_found


def get_rollout_state():
    application_timeline = query_application_timeline_list_query()
    releases = application_timeline['gitopsReleases']['edges']
    release = look_for_release_by_commit(releases, COMMIT_SHA)
    if not release:
        print(
            f"Release related to commit '{COMMIT_SHA}' couldn't be found. It's probably too old.")


    return rollout_state


def monitor_rollout():
    rollout_state = get_rollout_state()
    # Healthy, Progressing, Paused, Degraded
    rollout_status = rollout_state['phase'].lower()

    while rollout_status in ['progressing', 'paused']:
        print(f'{ rollout_status}, ', end="")
        rollout_state = get_rollout_state()
        rollout_status = rollout_state['phase'].lower()
        time.sleep(5)

    print("Rollout State:")
    print(json.dumps(rollout_state, indent=4), "\n")
    print(f'Rollout Status --> { rollout_status }')
    export_variable(CF_STEP_NAME, rollout_status)

    if rollout_status in ['degraded']:
        raise Exception(f'Rollout  status: {rollout_status}')


def get_account_id():
    account_id = ""
    url = 'https://g.codefresh.io/api/user'
    headers = {'Authorization': CF_API_KEY,
               'content-type': 'application/json', 'Accept-Charset': 'UTF-8'}
    response = requests.get(url,  headers=headers)
    user_info = response.json()
    account_name = user_info['activeAccountName']
    account_id = [account['id'] for account in user_info['account']
                  if account['name'] == account_name][0]
    return account_id


def rollout_exists():
    result = False
    rollout_state = get_rollout_state()
    rollout_status = rollout_state.get('phase')
    
    max_retries = 192
    retry_counter = 0
    while rollout_status == None and retry_counter < max_retries:
        retry_counter += 1
        print(
            f"App, Release or Rollout not found, please check your parameters. x{retry_counter} | ", end="")
        time.sleep(5)
        rollout_state = get_rollout_state()
        rollout_status = rollout_state.get('phase')
    if retry_counter > 0:
        print()

    if rollout_status != None:
        result = True
    return result


def export_variable(var_name, var_value):
    # if this script is executed in CF build
    if os.getenv('CF_BUILD_ID') != None:
        # exporting var when used as a freestyle step
        path = str(os.getenv('CF_VOLUME_PATH'))
        with open(path+'/env_vars_to_export', 'a') as a_writer:
            a_writer.write(var_name + "=" + var_value+'\n')
        # exporting var when used as a plugin
        with open('/meta/env_vars_to_export', 'a') as a_writer:
            a_writer.write(var_name + "=" + var_value+'\n')

    print("Exporting variable: "+var_name+"="+var_value)


def get_link_to_apps_dashboard():
    runtime = get_runtime()
    runtime_ns = runtime['runtime']['metadata']['namespace']
    ingress_host = runtime['runtime']['ingressHost']
    rollout_resource = query_rollout_resource(ingress_host)
    rollout_state = json.loads(rollout_resource['resource']['liveState'])
    revision = rollout_state['metadata']['annotations']['rollout.argoproj.io/revision']
    uid = rollout_state['metadata']['uid']
    namespace = rollout_state['metadata']['namespace']
    url_to_app = f"{CF_URL}/2.0/applications-dashboard/{RUNTIME_NAMESPACE}/{RUNTIME}/{APPLICATION}/current-state/tree"
    url_to_app += (f'?resourceName={ ROLLOUT }&resourceKind=Rollout&resourceVersion=v1alpha1&namespace={ namespace }'
                   f'&resourceGroup=argoproj.io&drawer=app-rollout-details&rdName={ ROLLOUT }&rdAppName={ APPLICATION }'
                   f'&rdAppNamespace={ runtime_ns }&rdRevision={ revision }&rdRuntime={ RUNTIME }&rdUID={ uid }')

    global CF_ACCOUNT_ID
    CF_ACCOUNT_ID = get_account_id()
    if CF_ACCOUNT_ID != "":
        url_to_app += f'&activeAccountId={ CF_ACCOUNT_ID }'

    return url_to_app


################################################################################

if __name__ == "__main__":
    main()
