#!/usr/bin/env python
import os, sys, subprocess, json, argparse, time
import rethinkdb as r
from common import *

def container_ip(cid):
    inspect = run_js('docker inspect '+cid)
    return only(inspect)['NetworkSettings']['IPAddress']

def lookup_registry_port(cid):
    inspect = run_js('docker inspect '+cid)
    return only(only(inspect)['NetworkSettings']['Ports']['5000/tcp'])['HostPort']

def main():
    parser = argparse.ArgumentParser(description='number of workers')
    parser.add_argument('--workers', '-w', default='1')
    args = parser.parse_args()

    cluster_dir = os.path.join(SCRIPT_DIR, 'cluster')
    if os.path.exists(cluster_dir):
        print 'Cluster already running!'
        sys.exit(1)
    os.mkdir(cluster_dir)

    # start registry
    c = 'docker run -d -p 5000 registry:2'
    cid = run(c).strip()
    registry_ip = container_ip(cid)
    registry_port = lookup_registry_port(cid)
    config_path = os.path.join(cluster_dir, 'registry.json')
    config = {'cid': cid,
              'ip': registry_ip,
              'host_port': registry_port}
    wrjs(config_path, config)
    print 'started registry ' + registry_ip + ':5000 (or localhost:' + registry_port + ')'
    print '='*40

    # start workers
    workers = []
    assert(int(args.workers) > 0)
    for i in range(int(args.workers)):
        config_path = os.path.join(cluster_dir, 'worker-%d.json' % i)
        config = {'registry_host': registry_ip,
                  'registry_port': '5000'}
        if i > 0:
            config['rethinkdb_join'] = workers[0]['ip']+':29015'

        wrjs(config_path, config)
        volumes = [('/sys/fs/cgroup', '/sys/fs/cgroup'),
                   (config_path, '/open-lambda-config.js')]
        c = 'docker run -d --privileged <VOLUMES> lambda-node'
        c = c.replace('<VOLUMES>', ' '.join(['-v %s:%s'%(host,guest)
                                             for host,guest in volumes]))
        cid = run(c).strip()
        config['cid'] = cid
        config['ip'] = container_ip(cid)
        wrjs(config_path, config, atomic=True)

        info_path = os.path.join(cluster_dir, 'worker-info-%d.json' % i)
        print 'started worker ' + config['ip']
        workers.append(config)

    # wait for rethinkdb
    print '='*40
    for i in range(10):
        try:
            r.connect(workers[0]['ip'], 28015).repl()
            up = len(list(r.db('rethinkdb').table('server_status').run()))
            if up < len(workers):
                print '%d of %d rethinkdb instances are ready' % (up, len(workers))
        except:
            print 'waiting for first rethinkdb instance to come up'
        time.sleep(1)
    print 'all rethinkdb instances are ready'

    # print directions
    print '='*40
    print 'Push images to OpenLambda registry as follows (or similar):'
    print 'IMG=hello && docker tag $IMG localhost:%s/$IMG; docker push localhost:%s/$IMG' % (registry_port, registry_port)
    print '='*40
    print 'Send requests as follows (or similar):'
    print "IMG=hello && curl -X POST %s:8080/runLambda/$IMG -d '{}'" % workers[-1]['ip']

if __name__ == '__main__':
    main()