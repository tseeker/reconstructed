reconstructed
=============

`reconstructed` is an Ansible inventory plugin which can be used to generate
group hierarchies and place hosts within them based solely on host facts.
This allows functionality similar to what the [ansible.builtin.add_host](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/add_host_module.html)
module can provide, but it is available during inventory construction rather
than playbook execution.

Installation from Ansible Galaxy
--------------------------------

You can install the latest version from Ansible Galaxy repository.

```bash
ansible-galaxy collection install -U tseeker.reconstructed
```

If you are using a *requirements.yml* file to download collections and roles,
you can use these lines:

```yaml
collections:
  - tseeker.reconstructed
```

Usage
-----

A `reconstructed` script can be added to the inventory by creating a YAML
file in the inventory, with the following structure:

```yaml
---
plugin: tseeker.reconstructed.reconstructed
instructions:
  - action: ...
  - action: ...
    # ...
```

Script actions are somewhat similar to playbook tasks. Once a script has been
added, it will be executed once for each host in the input inventory.

Each action record in a script must include an `action` field, which describes
the action to perform. In addition, it may include fields which contain the
action's details, as well as fields which implement various controls that
apply to an action (loops, local variables, etc).

The script can manipulate and use host facts. In addition, local variables
which do not pollute the inventory are used automatically for e.g. loops, and
can be defined manually.

### Actions

The following actions may be used in a `reconstructed` script.

#### add_child

This action adds an existing group to the set of another existing group's
children.

It supports the following fields.

  * `group` must contain the name of the parent group, or a Jinja template
    that evaluates to that name. The group must exist.
  * `child` must contain the name of the child group, or a Jinja template
    that evaluates to that name. The group must exist.

#### add_host

The `add_host` action can be used to add the inventory host currently being
processed to a group.

The following field is supported.

  * `group` must contain the name of the group to add the host to. It may
    be a Jinja template. The group in question must exist.

#### block

The `block` action can be used to group multiple actions and to support error
recovery, behaving in many ways like the playbooks' `block`. The following
fields may be used.

  * `block` contains the block's main list of instructions.
  * `rescue` contains a list of instructions that will be executed if an
    error occurs while executing the main list. The `reconstructed_error`
    local variable will contain the message of the error that caused the
    `rescue` list to be executed. This field may be omitted.
  * `always` contains a list of instructions that will be executed after
    both other lists, independently of any error. This field may be omitted.

#### create_group

The `create_group` action creates an inventory group. In addition, it may
specify the new group's parent and add the current host to the group.

If the group already exists, no error will be raised. The group will be added
to the specified parent and the host will be added to the group if requested.

The following fields are supported.

  * `group` contains the name of the group. It must be present and may contain
    a Jinja template.
  * `parent` may contain the name of an additional group to which the new
    group will be added as a child. The group in question must exist. This
    field is optional and may contain a Jinja template.
  * If the `add_host` field is present, it may contain a boolean which will
    determine whether the current inventory host must be added to the group.

#### fail

This action causes the script to fail immediately. The following field may be
used:

  * `msg` may contain a message (or a Jinja template resulting in a message)
    to write to the output. By default the message will be `fail requested`
    followed by the name of the current host.

#### rename_host

This action changes the name of the current host. It can only be executed once
for each host. The actual renaming will occur after the script has completed
its execution. It requires the following field:

  * `name`: the new name of the host.

#### set_fact

This action sets an Ansible fact associated to the current host. The following
fields must be set:

  * `name` is the name of the fact to set, or a Jinja template returning the
    name. It must represent a valid fact name.
  * `value` is the fact's new value, or a template computing it.

#### set_var

This action sets a local variable. Local variables are only kept for the
duration of the script's execution for a given host. A local variable will
hide a fact by the same name.

The following fields are required:

  * `name` is the name of the fact to set, or a Jinja template returning the
    name. It must result in a valid fact name.
  * `value` is the variable's new value, or a template computing it.

#### stop

The `stop` action interrupts the execution of the script for the current host.
It requires no additional information.

### Control fields

The following additional fields may be added to any action record to alter its
behaviour.

#### run_once

If this field is set to a ``true``, it will cause the action to be executed
only once.

#### loop and loop_var

The `loop` field may contain a list or a Jinja template that evaluates to a
list. The action record will be repeated for each item in the list, with a
local variable set to the value of the item.

By default the variable that contains the item is called `item`. However it
is possible to add a `loop_var` field containing a valid variable name to
change it. This variable will be restored to its previous state once the loop
is finished.

#### vars

The `vars` field may contain a table of local variables to set for the duration
of the action. The table's keys are variable names, and its values will be
evaluated using Jinja. During a loop, variables will be evaluated evaluated
once for each loop iteration. Once the action is finished, the local variables
defined using `vars` will disappear.

#### when

The `when` field may be used to check a condition and prevent the execution
of the action it is bound to if the condition isn't satisfied. The condition
is evaluated once for each iteration of a loop. All local variables defined
using `vars` are available for use in the condition.

## To do

  * `create_group.add_host` should allow Jinja templates
  * Add a `debug` action
