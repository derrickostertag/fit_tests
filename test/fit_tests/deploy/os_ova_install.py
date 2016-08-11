'''
Copyright 2015, EMC, Inc.

Author(s):
George Paulos

This script installs blank OVA template.
'''

import os
import sys
import subprocess
# set path to common libraries
sys.path.append(subprocess.check_output("git rev-parse --show-toplevel", shell=True).rstrip("\n") + "/test/fit_tests/common")
import fit_common
import pdu_lib

class os_ova_install(fit_common.unittest.TestCase):
    def test01_install_ova_template(self):
        ovafile = fit_common.GLOBAL_CONFIG['repos']['install']['template']
        # Check for ovftool
        self.assertEqual(fit_common.subprocess.call('which ovftool', shell=True), 0, "FAILURE: 'ovftool' not installed.")
        # Ping for valid ESXi host
        self.assertEqual(fit_common.subprocess.call('ping -c 1 ' + fit_common.ARGS_LIST['hyper'], shell=True), 0, "FAILURE: ESXi hypervisor not found.")
        # Shutdown previous ORA
        if fit_common.subprocess.call('ping -c 1 ' + fit_common.ARGS_LIST['ora'], shell=True) == 0:
            fit_common.remote_shell('shutdown -h now')
            fit_common.time.sleep(5)

        # Run probe to check for valid OVA file
        rc = fit_common.subprocess.call("ovftool " + ovafile, shell=True)
        self.assertEqual(rc, 0,'Invalid or missing OVA file: ' + ovafile)

        # this clears the hypervisor ssh key from ~/.ssh/known_hosts
        subprocess.call(["touch ~/.ssh/known_hosts;ssh-keygen -R "
                         + fit_common.ARGS_LIST['hyper']  + " -f ~/.ssh/known_hosts >/dev/null 2>&1"], shell=True)

        # Find correct hypervisor credentials by testing each entry in the list
        cred_list = fit_common.GLOBAL_CONFIG['credentials']['hyper']
        for entry in cred_list:
            uname = entry['username']
            passwd = entry['password']
            (command_output, exitstatus) = \
                fit_common.pexpect.run(
                                "ssh -q -o StrictHostKeyChecking=no -t " + uname + "@"
                                + fit_common.ARGS_LIST['hyper'] + " pwd",
                                withexitstatus=1,
                                events={"assword": passwd + "\n"},
                                timeout=20, logfile=None)
            if exitstatus == 0:
                break

        # Run OVA installer
        print '**** Deploying OVA file on hypervisor ' + fit_common.ARGS_LIST['hyper']
        rc = subprocess.call("ovftool --X:injectOvfEnv --overwrite "
                             "--powerOffTarget --skipManifestCheck -q "
                             "--net:'ADMIN'='VM Network' "
                             "--net:'CONTROL'='Control Network' "
                             "--net:'PDU'='PDU Network' "
                             "--name='ora-stack-" + fit_common.ARGS_LIST['stack'] + "' "
                             "--noSSLVerify "
                             + ovafile
                             + " vi://" + uname + ":" + passwd + "@"
                             + fit_common.ARGS_LIST['hyper'], shell=True)
        # Check for successful completion
        if rc > 0:
            print 'OVA installer failed at host: ' + fit_common.ARGS_LIST['hyper'] + "Exiting..."
            sys.exit(255)

        # Wait for VM to settle
        fit_common.countdown(30)
        # Install MAC address by editing OVA .vmx file, then startup VM
        esxi_command = "export fullpath=`find vmfs -name ora-stack-" + fit_common.ARGS_LIST['stack'] + "*.vmx`;" \
                       "for file in $fullpath;" \
                       "do " \
                       "export editline=`cat $file |grep \\\'ethernet0.generatedAddress =\\\'`;" \
                       "export editcmd=\\\'/\\\'$editline\\\'\/ c\\\ethernet0.address = \\\"" + fit_common.STACK_CONFIG[fit_common.ARGS_LIST['stack']]['ovamac'] + "\\\"\\\';" \
                       "sed -i \\\"$editcmd\\\" $file;" \
                       "sed -i \\\'/ethernet0.addressType = \\\"vpx\\\"/ c\\\ethernet0.addressType = \\\"static\\\"\\\' $file;" \
                       "done;" \
                       "sleep 5;" \
                       "export vmidstring=`vim-cmd vmsvc/getallvms |grep ora-stack-" + fit_common.ARGS_LIST['stack'] + "`;" \
                       "for vmid in $vmidstring;" \
                       "do " \
                       "vim-cmd vmsvc/power.on $vmid;" \
                       "exit $?;" \
                       "done;"

        (command_output, exitstatus) = \
            fit_common.pexpect.run(
                            "ssh -q -o StrictHostKeyChecking=no -t " + uname + "@"
                            + fit_common.ARGS_LIST['hyper'] + " " + esxi_command,
                            withexitstatus=1,
                            events={"assword": passwd + "\n"},
                            timeout=20, logfile=sys.stdout)
        if exitstatus > 0:
            print "MAC address processing failed. Exiting..."
            sys.exit(255)

        # Poll the OVA via ping
        for dummy in range(0, 30):
            rc = subprocess.call("ping -c 1 -w 5 " + fit_common.ARGS_LIST['ora'], shell=True)
            if rc == 0:
                break
            else:
                fit_common.time.sleep(10)
        self.assertEqual(rc, 0, "VM did not activate.")
        # Sync time on ORA
        localdate = fit_common.subprocess.check_output("date +%s", shell=True)
        fit_common.remote_shell("/bin/date -s @" + localdate.replace("\n", "") + ";/sbin/hwclock --systohc")

    def test02_power_off_nodes(self):
        print "**** Configuring power interface: "
        self.assertTrue(pdu_lib.config_power_interface(), "Failed to configure power interface")
        fit_common.time.sleep(15)
        # ServerTech PDU case
        if pdu_lib.check_pdu_type() != "Unknown":
            print "**** Installing snmp package: "
            self.assertTrue(pdu_lib.install_snmp(), "Failed to install snmp")
            print "**** PDU found, powering off compute nodes."
            self.assertTrue(pdu_lib.pdu_control_compute_nodes("off"), 'Failed to power off all outlets')
        # no PDU case
        else:
            print '**** No supported PDU found, using IMPI to restart, some nodes may not discover.'

if __name__ == '__main__':
    fit_common.unittest.main()
