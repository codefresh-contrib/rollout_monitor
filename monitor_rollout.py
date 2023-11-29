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
MULTI_CLUSTER_ROLLOUT_ID = os.getenv('MULTI_CLUSTER_ROLLOUT_ID')
RELEASES_TO_RETRIEVE = int(os.getenv('RELEASES_TO_RETRIEVE', '20'))
# In minutes. How much time to check for the existence of the app|commit|rollout.
SEARCH_TIMEOUT = int(os.getenv('SEARCH_TIMEOUT', '20'))

# Defaults | constants
CF_URL = os.getenv('CF_URL', 'https://g.codefresh.io')
CF_API_KEY = os.getenv('CF_API_KEY')
CF_STEP_NAME = os.getenv('CF_STEP_NAME', 'STEP_NAME')
CHECK_INTERVAL = 5  # interval in seconds between each check in the monitor loop

# Inferred during execution time
CF_ACCOUNT_ID = ""  # It will be infered later, using the CF_API_KEY
RUNTIME_NAMESPACE = ""  # It will be infered later, during execution
RUNTIME_INGRESS_HOST = ""


################################################################################


def main():
    parameters = {
        "RUNTIME": RUNTIME,
        "APPLICATION": APPLICATION,
        "ROLLOUT": ROLLOUT,
        "MULTI_CLUSTER_ROLLOUT_ID": MULTI_CLUSTER_ROLLOUT_ID
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
    runtime_ingress_host = runtime['runtime']['ingressHost']
    global RUNTIME_NAMESPACE
    RUNTIME_NAMESPACE = str(runtime_ns)
    global RUNTIME_INGRESS_HOST
    RUNTIME_INGRESS_HOST = str(runtime_ingress_host)


def look_for_release_by_commit(releases, commit_sha):
    release_found = {}
    for release in releases:
        release_commit = release['node']['application']['status']['revision']
        if release_commit == commit_sha:
            release_found = release['node']
    return release_found


def extract_multi_cluster_rollout_id_from_release(release):
    multi_cluster_rollout_id = ''
    commitMessage = release['node']['application']['status']['commitMessage']
    lines = commitMessage.split('\n')
    # print(f'lines = {lines}')
    multi_cluster_rollout_id_key_pair = [
        s for s in lines if "multiClusterRolloutId" in s][-1]
    # print(f'multi_cluster_rollout_id_key_pair => {multi_cluster_rollout_id_key_pair}')
    multi_cluster_rollout_id = multi_cluster_rollout_id_key_pair.split(':')[
        1].strip()
    print(f'multi_cluster_rollout_id => {multi_cluster_rollout_id}')
    return multi_cluster_rollout_id


def look_for_release_by_multi_cluster_rollout_id(releases, multi_cluster_rollout_id):
    release_found = {}
    for release in releases:
        release_multi_cluster_rollout_id = extract_multi_cluster_rollout_id_from_release(
            release)
        if release_multi_cluster_rollout_id == multi_cluster_rollout_id:
            release_found = release['node']
    return release_found


def look_for_rollout_by_rollout_name(rollouts, rollout_name):
    rollout_found = {}
    for rollout in rollouts:
        if rollout_name == rollout['to']['name']:
            rollout_found = rollout['to']
    return rollout_found

# FROM RUNTIME


def get_rollout_state():
    rollout_state = {}
    rollout_resource = query_rollout_resource(RUNTIME_INGRESS_HOST)

    # print('rollout_resource =>')
    # print(json.dumps(rollout_resource, indent=4))
    if rollout_resource['resource']['liveState'] != '':
        rollout_state = json.loads( rollout_resource.get('resource', {}).get('liveState', {}) )
    multi_cluster_rollout_id = rollout_state.get('metadata', {}).get('labels', {}).get('multiClusterRolloutId', '')

    if multi_cluster_rollout_id == MULTI_CLUSTER_ROLLOUT_ID:
        rollout_state = {
            "name": rollout_state['metadata']['name'],
            "namespace": rollout_state['metadata']['namespace'],
            "resourceVersion": rollout_state['metadata']['resourceVersion'],
            "uid": rollout_state['metadata']['uid'],
            "labels": rollout_state['metadata']['labels'],
            "phase": rollout_state['status']['phase'],
            "readyReplicas": rollout_state['status']['readyReplicas'],
            "replicas": rollout_state['status']['replicas']
        }
    else:
        print(
            f"Rollout with multiClusterRolloutId = '{MULTI_CLUSTER_ROLLOUT_ID}' couldn't be found (yet)")

    return rollout_state


def monitor_rollout():
    rollout_state = get_rollout_state()
    # Healthy, Progressing, Paused, Degraded, Terminated
    rollout_status = rollout_state['phase'].lower()

    while rollout_status in ['progressing', 'paused']:
        print(f'{ rollout_status}, ', end="")
        rollout_state = get_rollout_state()
        rollout_status = rollout_state['phase'].lower()
        time.sleep(CHECK_INTERVAL)

    print("\nRollout State:")
    print(json.dumps(rollout_state, indent=4), "\n")
    print(f'Rollout Status --> { rollout_status }')
    export_variable(CF_STEP_NAME, rollout_status)

    if rollout_status in ['degraded', 'terminated']:
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

    max_retries = (SEARCH_TIMEOUT * 60) / CHECK_INTERVAL
    retry_counter = 0
    while rollout_status == None and retry_counter < max_retries:
        retry_counter += 1
        print(
            f"Rollout not found, please check your parameters. x{retry_counter} | ", end="")
        time.sleep(CHECK_INTERVAL)
        rollout_state = get_rollout_state()
        rollout_status = rollout_state.get('phase')
    if retry_counter > 0:
        print("\n\n")

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
