#!/usr/bin/env python
# -*- coding:utf8 -*-
"""Generate JA3 fingerprints from PCAPs using Python."""


import argparse
import dpkt
import json
import socket
import struct
import hashlib
import win_inet_pton # for windows

__author__ = "Tommy Stallings"
__copyright__ = "Copyright (c) 2017, salesforce.com, inc."
__credits__ = ["John B. Althouse", "Jeff Atkinson", "Josh Atkins"]
__license__ = "BSD 3-Clause License"
__version__ = "1.0.0"
__maintainer__ = "Tommy Stallings, Brandon Dixon"
__email__ = "tommy.stallings@salesforce.com"


GREASE_TABLE = {0x0a0a: True, 0x1a1a: True, 0x2a2a: True, 0x3a3a: True,
                0x4a4a: True, 0x5a5a: True, 0x6a6a: True, 0x7a7a: True,
                0x8a8a: True, 0x9a9a: True, 0xaaaa: True, 0xbaba: True,
                0xcaca: True, 0xdada: True, 0xeaea: True, 0xfafa: True}
# GREASE_TABLE Ref: https://tools.ietf.org/html/draft-davidben-tls-grease-00
SSL_PORT = 443
TLS_HANDSHAKE = 22


def convert_ip(value):
    """Convert an IP address from binary to text.

    :param value: Raw binary data to convert
    :type value: str
    :returns: str
    """
    try:
        # return socket.inet_ntop(socket.AF_INET, value)
        return win_inet_pton.inet_ntop(socket.AF_INET, value) # this for windows
    except ValueError:
        # return socket.inet_ntop(socket.AF_INET6, value)
        return win_inet_pton.inet_ntop(socket.AF_INET6, value) # this for windows


def parse_variable_array(buf, byte_len):
    """Unpack data from buffer of specific length.

    :param buf: Buffer to operate on
    :type buf: bytes
    :param byte_len: Length to process
    :type byte_len: int
    :returns: bytes, int 返回具体数据部分，和最后位置
    """
    _SIZE_FORMATS = ['!B', '!H', '!I', '!I'] #将网络字节流解析成对应字节数
    assert byte_len <= 4
    size_format = _SIZE_FORMATS[byte_len - 1]
    padding = b'\x00' if byte_len == 3 else b''
    size = struct.unpack(size_format, padding + buf[:byte_len])[0] #data的具体大小
    data = buf[byte_len:byte_len + size]

    return data, size + byte_len


def ntoh(buf):
    """Convert to network order.

    :param buf: Bytes to convert
    :type buf: bytearray
    :returns: int
    """
    if len(buf) == 1:
        return buf[0]
    elif len(buf) == 2:
        return struct.unpack('!H', buf)[0]
    elif len(buf) == 4:
        return struct.unpack('!I', buf)[0]
    else:
        raise ValueError('Invalid input buffer size for NTOH')


def convert_to_ja3_segment(data, element_width):
    """Convert a packed array of elements to a JA3 segment.

    :param data: Current PCAP buffer item
    :type: str
    :param element_width: Byte count to process at a time
    :type element_width: int
    :returns: str
    """
    int_vals = list()
    data = bytearray(data)
    if len(data) % element_width:# 长度 mod 2
        message = '{count} is not a multiple of {width}'
        message = message.format(count=len(data), width=element_width)
        raise ValueError(message)

    for i in range(0, len(data), element_width):
        element = ntoh(data[i: i + element_width])# 按element_width字节数解析字节流
        if element not in GREASE_TABLE:
            int_vals.append(element)

    return "-".join(str(x) for x in int_vals)

def getServerName(data):
    datatmp = bytearray(data)
    datalen=ntoh(datatmp[1: 3])
    # print len(datatmp[datalen:])
    # 第一字节表明是host_name，第二三字节是name长度，第四字节到最后是name
    snstr=struct.unpack('!{}s'.format(datalen), datatmp[3:])[0]
    return  snstr

def process_extensions(client_handshake):
    """Process any extra extensions and convert to a JA3 segment.

    :param client_handshake: Handshake data from the packet
    :type client_handshake: dpkt.ssl.TLSClientHello
    :returns: list
    """
    if not hasattr(client_handshake, "extensions"):
        # Needed to preserve commas on the join
        return ["", "", ""],""

    exts = list()
    elliptic_curve = ""
    elliptic_curve_point_format = ""
    serverName=""
    for ext_val, ext_data in client_handshake.extensions:# ext_val是Type，ext_data是除Type外所有数据
        if not GREASE_TABLE.get(ext_val):
            exts.append(ext_val)
        if ext_val == 0x0a:# type == 10 获取椭圆加密曲线点
            a, b = parse_variable_array(ext_data, 2)# 跳过 Length，2字节
            # Elliptic curve points (16 bit values)
            elliptic_curve = convert_to_ja3_segment(a, 2)
        elif ext_val == 0x0b:# type == 11 获取椭圆曲线模板
            a, b = parse_variable_array(ext_data, 1)
            # Elliptic curve point formats (8 bit values)
            elliptic_curve_point_format = convert_to_ja3_segment(a, 1)
        elif ext_val == 0x00:# type ==0 获取 ssl server name
            a, b = parse_variable_array(ext_data, 2)  # 跳过 Length，2字节,a截断数据
            serverName=getServerName(a)
        else:
            continue

    results = list()
    results.append("-".join([str(x) for x in exts]))
    results.append(elliptic_curve)
    results.append(elliptic_curve_point_format)
    return results,serverName


def process_pcap(pcap, any_port=False):
    """Process packets within the PCAP.

    :param pcap: Opened PCAP file to be processed
    :type pcap: dpkt.pcap.Reader
    :param any_port: Whether or not to search for non-SSL ports
    :type any_port: bool
    """
    results = list()
    for timestamp, buf in pcap:
        try:
            eth = dpkt.ethernet.Ethernet(buf)# 链路层数据
        except Exception:
            continue

        if not isinstance(eth.data, dpkt.ip.IP):
            # We want an IP packet
            continue
        if not isinstance(eth.data.data, dpkt.tcp.TCP):
            # TCP only
            continue

        ip = eth.data   #IP层数据
        tcp = ip.data   #TCP数据

        if not (tcp.dport == SSL_PORT or tcp.sport == SSL_PORT or any_port):
            # Doesn't match SSL port or we are picky
            continue
        if len(tcp.data) <= 0:
            continue

        tls_handshake = bytearray(tcp.data) # handshake 数据
        if tls_handshake[0] != TLS_HANDSHAKE:
            continue

        records = list()

        try:
            records, bytes_used = dpkt.ssl.tls_multi_factory(tcp.data)#解析多个TLS record
        except dpkt.ssl.SSL3Exception:
            continue
        except dpkt.dpkt.NeedData:
            continue

        if len(records) <= 0:
            continue

        '''
        record 包括头部分/数据部分
        头部分： Content Type/Version/Length
        数据部分： handshake Protocal
        '''
        for record in records:
            if record.type != TLS_HANDSHAKE:
                continue
            if len(record.data) == 0:
                continue
            client_hello = bytearray(record.data)
            if client_hello[0] != 1:
                # We only want client HELLO
                continue
            try: #判断数据部分是否仍是 Client Hello包
                handshake = dpkt.ssl.TLSHandshake(record.data)
            except dpkt.dpkt.NeedData:
                # Looking for a handshake here
                continue
            if not isinstance(handshake.data, dpkt.ssl.TLSClientHello):
                # Still not the HELLO
                continue

            client_handshake = handshake.data
            buf, ptr = parse_variable_array(client_handshake.data, 1)
            buf, ptr = parse_variable_array(client_handshake.data[ptr:], 2)
            ja3 = [str(client_handshake.version)]

            # Cipher Suites (16 bit values)每个Cipher大小是2字节
            ja3.append(convert_to_ja3_segment(buf, 2))
            tmpJA3,servername=process_extensions(client_handshake)
            ja3 += tmpJA3
            ja3 = ",".join(ja3)
            md5=hashlib.md5()
            md5.update(ja3.encode())
            record = {"source_ip": convert_ip(ip.src),
                      "destination_ip": convert_ip(ip.dst),
                      "source_port": tcp.sport,
                      "destination_port": tcp.dport,
                      "ja3": ja3,
                      "ja3_digest": md5.hexdigest(),
                      "server_name":servername,
                      "timestamp": timestamp}
            results.append(record)

    return results

def saveFunc(name,data):
    with open(name,'w') as fp:
        json.dump(data,fp,indent=4)

def main():
    """Intake arguments from the user and print out JA3 output."""
    # desc = "A python script for extracting JA3 fingerprints from PCAP files"
    # parser = argparse.ArgumentParser(description=(desc))
    # parser.add_argument("pcap", help="The pcap file to process")
    # help_text = "Look for client hellos on any port instead of just 443"
    # parser.add_argument("-a", "--any_port", required=False,
    #                     action="store_true", default=False,
    #                     help=help_text)
    # help_text = "Print out as JSON records for downstream parsing"
    # parser.add_argument("-j", "--json", required=False, action="store_true",
    #                     default=False, help=help_text)
    # args = parser.parse_args()

    # Use an iterator to process each line of the file
    output = None
    # with open(args.pcap, 'rb') as fp:
    filename="test_ssl_jt"
    filepath='F:\\testfile\\'
    with open(filepath+filename+".pcap", 'rb') as fp:
        try:
            capture = dpkt.pcap.Reader(fp)
        except ValueError as e:
            raise Exception("File doesn't appear to be a PCAP: %s" % e)
        output = process_pcap(capture, any_port=False)
    savename=filename+"_save.json"
    saveFunc(filepath+savename,output)
    # if args.json:
    if 1==1:
        output = json.dumps(output, indent=4, sort_keys=True)
        print(output)
    else:
        for record in output:
            tmp = '[{dest}:{port}] JA3: {segment} --> {digest}'
            tmp = tmp.format(dest=record['destination_ip'],
                             port=record['destination_port'],
                             segment=record['ja3'],
                             digest=record['ja3_digest'])
            print(tmp)


if __name__ == "__main__":
        main()
