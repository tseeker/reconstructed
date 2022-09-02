reconstructed
=============

An Ansible plugin that can generate structured inventories programmatically.

This is a work in progress. I will make this README more useful later, provided
I just don't forget about this whole thing.

A `reconstructed` inventory executes a list of instructions that is read
from the `instructions` YAML field. Each instruction is a table with some
minimal control flow (`when` and `loop` keywords that work mostly like their
playbook cousins), an `action` field that contains the name of the instruction
to execute, and whatever fields are needed for the instruction.

The following actions are supported:

  * `create_group` creates a group. The name of the group must be
    provided using the `group` field, which must be a valid name or a
    Jinja template that evaluates to a valid name.

  * `add_child` adds a child group to another group. The name of the
    group being added must be provided in the `child` entry, while
    the name of the parent must be provided in the `group` entry. Both
    groups must exist. In addition, the names may be specified using
    Jinja templates.

  * `add_host` adds the current inventory host to a group. The name
    of the group must be provided in the `group` entry. The group
    must exist.

  * `fail` causes the computations for the current host to stop with
    an error. The error message may be specified in the `message`
    entry; if present, it will be evaluated using Jinja.

  * `set_fact` and `set_var` create a fact and a local variable,
    respectively. Local variables will only be kept during the execution
    of the script for the current host, while facts will be added to the
    host's data. The `name` entry specifies the name of the fact or
    variable while the `value` entry specifies its value. Both may be
    Jinja templates.

  * `stop` stops processing the list of instructions for the current
    host.

In addition, the `block` can be used to repeat multiple instructions or make
them obey a single conditional. The instruction must include a `block` field,
containing the list of instructions which are part of the block. It may have
a `rescue` field, containing a list of instructions which will be executed on
error, and `always`, which may contain a list of instructions to execute in
all cases. If the `locals` field is defined, it must contain a table of local
variables to define. Any local variable defined by the instructions under
`block`, `rescue` or `always` will go out of scope once the block finishes
executing.

A somewhat silly example can be found in the `example` directory. Trying to
execute it using `ansible-inventory --graph` results in the following output.

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
