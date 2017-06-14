# This Bro script adds JA3 to the Bro Intel Framework as Intel::JA3
#
# Copyright (c) 2017, salesforce.com, inc.
# All rights reserved.
# Licensed under the BSD 3-Clause license. 
# For full license text, see LICENSE.txt file in the repo root  or https://opensource.org/licenses/BSD-3-Clause

module Intel;

export {
    redef enum Intel::Type += { Intel::JA3 };
}

export {
    redef enum Intel::Where += { SSL::IN_JA3 };
}

event ssl_server_hello (c: connection, version: count, possible_ts: time, server_random: string, session_id: string, cipher: count, comp_method: count)
	{
	Intel::seen([$indicator=c$ssl$ja3, $indicator_type=Intel::JA3, $conn=c, $where=SSL::IN_JA3]);
	}