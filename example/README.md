reconstructed example
=====================

The example in this directory generates a graph of hosts, organised based on
the contents of a variable called ``inv__data`` associated to each host
statically in the ``inventory/00-data.yml`` file. The main ``reconstructed``
script, located in ``inventory/01-test-reconstructed.yml``, is executed once
for each host. It creates the various groups at the appropriate locations,
defines additional facts, and adds hosts to the groups.

The example can be executed using :

```
ansible-galaxy collection install .. -p ./collections
ansible-inventory --playbook-dir . --graph
```

When executed, ``localhost`` will be skipped as it doesn't have the
``inv__data`` fact.

Two hosts in there, ``evil-vm`` and ``evil-but-nicer-vm``, are meant to
illustrate the ``fail`` action as well as error recovery.

The rest of the hosts correspond to two instances of a LDAP cluster, in which
two hosts are used as the frontend, two hosts as the read-only replicas, and
the last one as the master. Groups are generated based on the environment,
network, and failover stack, as well as service, components of the service,
and instances of a service.

Below is the output that should be obtained.

```
[WARNING]: reconstructed - error on host evil-vm: evil-vm is obviously evil,
skipping.
@all:
  |--@managed:
  |  |--@by_environment:
  |  |  |--@env_dev:
  |  |  |  |--vm00
  |  |  |  |--vm01
  |  |  |  |--vm02
  |  |  |  |--vm03
  |  |  |  |--vm04
  |  |  |  |--vm09
  |  |  |--@env_prod:
  |  |  |  |--vm05
  |  |  |  |--vm06
  |  |  |  |--vm07
  |  |  |  |--vm08
  |  |--@by_failover_stack:
  |  |  |--@fostack_1:
  |  |  |  |--vm00
  |  |  |  |--vm02
  |  |  |  |--vm05
  |  |  |  |--vm07
  |  |  |--@fostack_2:
  |  |  |  |--vm01
  |  |  |  |--vm03
  |  |  |  |--vm06
  |  |  |  |--vm08
  |  |  |--@no_failover:
  |  |  |  |--vm04
  |  |  |  |--vm09
  |  |--@by_network:
  |  |  |--@net_dev:
  |  |  |  |--vm00
  |  |  |  |--vm01
  |  |  |  |--vm02
  |  |  |  |--vm03
  |  |  |  |--vm04
  |  |  |--@net_infra:
  |  |  |  |--vm05
  |  |  |  |--vm06
  |  |  |  |--vm07
  |  |  |  |--vm08
  |  |  |  |--vm09
  |  |--@by_service:
  |  |  |--@svc_ldap:
  |  |  |  |--@svcm_ldap_back:
  |  |  |  |  |--@svcm_ldap_ro:
  |  |  |  |  |  |--vm02
  |  |  |  |  |  |--vm03
  |  |  |  |  |  |--vm07
  |  |  |  |  |  |--vm08
  |  |  |  |  |--@svcm_ldap_rw:
  |  |  |  |  |  |--vm04
  |  |  |  |  |  |--vm09
  |  |  |  |--@svcm_ldap_front:
  |  |  |  |  |--vm00
  |  |  |  |  |--vm01
  |  |  |  |  |--vm05
  |  |  |  |  |--vm06
  |--@reedmably_evil:
  |  |--evil-but-nicer-vm
  |--@ungrouped:
  |  |--evil-vm
  |  |--localhost
```
