# [Comware平台语料] 模板-comware通用脚本 #
# *-* encoding: utf-8 *-*
from pytest_atf import *
from pytest_atf.atf_globalvar import globalVar as gl
from atf_log.logger import logger
from AtfLibrary.utils import CDeviceUtil
from AtfLibrary.ipaddr import IPAddress
from conftest import CVarsAndFuncs

# 脚本对应用例的信息，case_no 必须与用例编号对应
module = 'RIR_20.1.5.48'
case_no = 'T127_P160636'

'''
==========================项目详细信息START============================================
 项目流水号           : NV202508210024

 项目名称             :【中低端路由器】【V9B83分支】【ADWAN分支方案】【5G冷备】请设备在SDWAN方案里支持备用链路，以支持5G链路冷备功能

 脚本开发作者         : hedongsheng/26058

 脚本开发时间         : 2025/11/28

 AIGC生成代码量（行） : 0

 生产耗时（人时）     : 4
==========================项目详细信息END==============================================

==========================当前脚本涉及到的关键功能命令行START==========================
 主测功能命令：
 rir link-backup enable
 辅助功能命令：
 rir link-group
==========================当前脚本涉及到的关键功能命令行END============================ 

=========================== 平台AIGC私域语料使用方法 START ============================
 Comware平台测试私域语料查询：
 1、TOPOX配置语料：通过TOPOX文件名呼出题词菜单，如输入：ROUTE_2.0.0_1.Topox，选中所需，Ctrl+Enter键获取内容
 2、综合场景语料：通过业务特性名呼出题词菜单，如输入：L3VPN，选中所需，Ctrl+Enter键获取内容
 3、测试仪语料：通过测试仪呼出题词菜单，如输入：测试仪，选中所需，Ctrl+Enter键获取内容
 4、Display检查语料：通过检查呼出题词菜单，如输入：检查，选中所需，Ctrl+Enter键获取内容
=========================== 平台AIGC私域语料使用方法  END ==============================
 AI_FingerPrint_UUID: 20251128-zK7CEyN9
'''

class TestClass:
    '''
    测试目的：测试RIR按组拉起冷备功能
    作者：hedongsheng/26058
    开发时间：2025/11/28
    修改记录：
    '''
    @classmethod
    def setup_class(cls):
        '''
        [场景化] RIR场景化
        '''
        gl.DUT1.send(f'''
            #
            ctrl+z
            sys
            #
            interface LoopBack 10
            ip address 50.50.50.20 255.255.255.255
            #                                                                                                                                                           
            interface Tunnel1 mode sdwan udp
            ip address unnumbered interface {gl.DUT1.PORT1.intf}
            source {gl.DUT1.PORT1.intf}
            tunnel out-interface {gl.DUT1.PORT1.intf}
            sdwan interface-id 2
            y
            sdwan routing-domain bbb id 20
            y
            sdwan transport-network aaa id 10
            y
            sdwan encapsulation udp-port 3000
            y
            #                                                                                                                                                           
            interface Tunnel2 mode sdwan udp
            ip address unnumbered interface {gl.DUT1.PORT2.intf}
            source {gl.DUT1.PORT2.intf}
            tunnel out-interface {gl.DUT1.PORT2.intf}
            sdwan interface-id 3
            y
            sdwan routing-domain bbb id 21
            y
            sdwan transport-network aaa id 11
            y
            sdwan encapsulation udp-port 3001
            y
            #                                                                                                                                                           
            interface Tunnel3 mode sdwan udp
            ip address unnumbered interface {gl.DUT1.PORT1.intf}
            source {gl.DUT1.PORT1.intf}
            sdwan interface-id 4
            y
            sdwan routing-domain bbb id 22
            y
            sdwan transport-network aaa id 12
            y
            sdwan encapsulation udp-port 3002
            y
            #
            bgp 200
            router-id 50.50.50.20	
            peer 50.50.50.10 as-number 200                                                                                                                                                        
            peer 50.50.50.10 connect-interface LoopBack10
            address-family ipv4 unicast
            import-route direct
            #
            address-family ipv4 tnl-encap-ext
            peer 50.50.50.10 enable
            #
            address-family l2vpn evpn
            undo policy vpn-target
            peer 50.50.50.10 enable
            peer 50.50.50.10 advertise encap-type sdwan
            quit
            quit
            #
            ssl client-policy plc1
            prefer-cipher rsa_aes_256_cbc_sha
            undo server-verify enable
            quit
            sdwan site-id 2
            y
            sdwan site-name shanghai
            sdwan device-id 2
            y
            sdwan system-ip LoopBack10
            y
            sdwan site-role cpe
            y
            sdwan ssl-client-policy plc1
            sdwan server system-ip 50.50.50.10 ip {gl.DUT2.PORT1.ip} port 1234 
            rir sdwan
            link-quality probe interval 10
            y
            link-select delay 10
            link-select suppress-period 60
            quit                                                                                                                                                                                                                                                                                                                                                                                                                               
        ''')

        gl.DUT2.send(f'''
             #
            ctrl+z
            sys
            #
            interface LoopBack 10
            ip address 50.50.50.10 255.255.255.255
            quit
            interface Tunnel1 mode sdwan udp
            ip address unnumbered interface {gl.DUT2.PORT1.intf}
            source {gl.DUT2.PORT1.intf}
            tunnel out-interface {gl.DUT2.PORT1.intf}
            sdwan interface-id 1
            y
            sdwan routing-domain bbb id 20
            y
            sdwan transport-network aaa id 10
            y
            sdwan encapsulation udp-port 3000
            y
            quit     
            interface Tunnel2 mode sdwan udp
            ip address unnumbered interface {gl.DUT2.PORT2.intf}
            source {gl.DUT2.PORT2.intf}
            tunnel out-interface {gl.DUT2.PORT2.intf}
            sdwan interface-id 2
            y
            sdwan routing-domain bbb id 21
            y
            sdwan transport-network aaa id 11
            y
            sdwan encapsulation udp-port 3001
            y
            quit
            interface Tunnel3 mode sdwan udp
            ip address unnumbered interface {gl.DUT2.PORT1.intf}
            source {gl.DUT2.PORT1.intf}
            sdwan interface-id 3
            y
            sdwan routing-domain bbb id 22
            y
            sdwan transport-network aaa id 12
            y
            sdwan encapsulation udp-port 3002
            y
            quit                                                                                                                                                                                                     
            bgp 200
            router-id 50.50.50.10
            peer 50.50.50.20 as-number 200
            peer 50.50.50.20 connect-interface LoopBack10
            address-family ipv4 unicast
            import-route direct
            quit
            address-family ipv4 tnl-encap-ext
            peer 50.50.50.20 enable
            peer 50.50.50.20 next-hop-local
            peer 50.50.50.20 reflect-client
            quit
            address-family l2vpn evpn
            undo policy vpn-target
            peer 50.50.50.20 enable
            peer 50.50.50.20 advertise encap-type sdwan
            ip vpn-instance vpn1
            peer 50.50.50.20 as-number 1
            address-family ipv4 unicast
            import-route direct
            peer 50.50.50.20 enable
            quit
            quit
            sdwan site-id 1
            y
            sdwan device-id 1
            y
            sdwan site-name shanghai
            sdwan system-ip LoopBack10
            y
            sdwan site-role rr
            y
            sdwan server port 1234
            sdwan server enable
            rir sdwan
            link-quality probe interval 10
            y
            link-select delay 10
            link-select suppress-period 60
            quit
        ''')

    @classmethod
    def teardown_class(cls):
        '''
        [场景化] 清除BGP EPE MPLS场景化
        '''
        gl.DUT1.send(f'''
            #
            ctrl+z
            sys
            #
            undo interface LoopBack 10
            undo interface Tunnel1
            #
            undo interface Tunnel3
            undo interface Tunnel4
            undo bgp 200
            y
            #
            undo ssl client-policy plc1
            undo sdwan site-id
            y
            #
            undo sdwan site-name
            undo sdwan device-id
            y 
            #
            undo sdwan system-ip
            y
            undo sdwan site-role
            y
            undo sdwan ssl-client-policy
            undo sdwan server system-ip 50.50.50.10 ip {gl.DUT2.PORT1.ip} port 1234
            undo rir sdwan
            y
        ''')

        gl.DUT2.send(f'''
            #
            ctrl+z
            sys
            #
            undo interface LoopBack 10
            undo interface Tunnel1
            #
            undo interface Tunnel2
            undo interface Tunnel3
            undo bgp 200
            y
            undo sdwan site-id
            y
            #
            undo sdwan site-name
            undo sdwan device-id
            y 
            #
            undo sdwan server enable
            undo sdwan system-ip
            y
            undo sdwan site-role
            y
            undo sdwan server port
            undo sdwan ssl-client-policy
            undo sdwan server system-ip 50.50.50.10 ip {gl.DUT2.PORT1.ip} port 1234
            undo rir sdwan
            y
        ''')

    def test_step_1(self):
        '''
        多链路不配置tunnel out-if测试(ipv6)
        '''
        gl.DUT1.send( f'''
          ctrl+zsystem-view
          interface Tunnel 4
          undo tunnel out-interface
          quit
          rir link-backup enable
          rir link-group aaa
          link-member interface Tunnel 1
          link-member interface Tunnel 4 standby
          quit
          ''')

        gl.DUT1.CheckCommand('开启冷备功能，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT2.intf}',
                             expect=["SDWAN source DOWN"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=10
                                  )

        gl.DUT1.send( f'''
          undo rir link-backup enable
          ''')
        gl.DUT1.CheckCommand('关闭冷备功能，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT1.intf}',
                             expect=["Current state:UP"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=3
                                  )

        gl.DUT1.send( f'''
          rir link-backup enable
          ''')
        gl.DUT1.CheckCommand('再次开启冷备功能，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT2.intf}',
                             expect=["SDWAN source DOWN"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=10
                                  )

        gl.DUT1.send( f'''
          rir link-group aaa
          link-member interface Tunnel 4
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，备链路变为主链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT1.intf}',
                             expect=["Current state:UP"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=3
                                  )

        gl.DUT1.send( f'''
          link-member interface Tunnel 4 standby
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，再变为备链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT2.intf}',
                             expect=["SDWAN source DOWN"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=10
                                  )
        
        gl.DUT1.send( f'''
          link-member interface Tunnel 1 standby
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，主链路变为备链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT1.intf}',
                             expect=["Current state:UP"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=3
                                  )

        gl.DUT1.send( f'''
          link-member interface Tunnel 1
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，再变为主链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT2.intf}',
                             expect=["SDWAN source DOWN"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=10
                                  )

        gl.DUT1.send( f'''
          undo link-member interface Tunnel 4
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，删除备链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT1.intf}',
                             expect=["Current state:UP"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=3
                                  )

        gl.DUT1.send( f'''
          link-member interface Tunnel 4 standby
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，再添加备链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT2.intf}',
                             expect=["SDWAN source DOWN"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=10
                                  )
        
        gl.DUT1.send( f'''
          undo link-member interface Tunnel 1
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，删除主链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT1.intf}',
                             expect=["Current state:UP"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=3
                                  )

        gl.DUT1.send( f'''
          link-member interface Tunnel 1
          quit
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，再添加主链路后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT2.intf}',
                             expect=["SDWAN source DOWN"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=10
                                  )

        gl.DUT1.send( f'''
          undo rir link-group aaa
          ''')
        gl.DUT1.CheckCommand('开启冷备功能，删除RIR链路组后，非同源sdwan隧道备链路out-if状态测试',
                             cmd=f'display interface {gl.DUT2.PORT1.intf}',
                             expect=["Current state:UP"],
                             relationship = 'and',
                             stop_max_attempt=3,
                             wait_fixed=3
                                  )


        

    
        




   
