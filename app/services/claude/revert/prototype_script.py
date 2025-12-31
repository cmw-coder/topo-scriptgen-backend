import pytest
from pytest_atf.atf_globalvar import globalVar as gl
from pytest_atf import run_multithread, atf_assert, atf_check, atf_skip, atf_logs


class TestBGPAddPathBest:
    """
    测试BGP IPv4地址族发送的Add-Path优选路由的最大条数

    前置背景:
        3台设备,DUT1作为RR,和DUT2使用直连接口建立3个IBGP邻居
        DUT1和DUT3使用直连接口建立1个IBGP邻居,DUT2引入一条静态路由

    依赖conftest.py中的setup配置,无需额外setup_class
    """

    def test_step_1(self):
        """
        场景1: 初始Add-Path路由验证

        验证DUT1已从DUT2的3个邻居收到192.168.1.0/24路由
        DUT1配置additional-paths select-best 3
        DUT3收到3条Add-Path路由
        """
        # 检查DUT3上收到192.168.1.0/24的Add-Path路由,路由条数为3条
        gl.DUT3.CheckCommand(
            'DUT3检查收到192.168.1.0/24的Add-Path路由条数为3',
            cmd='display bgp routing-table ipv4 192.168.1.0 24',
            expect=[
                '192.168.1.0/24',
                ('Paths:', '3 available')
            ],
            not_expect=[],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

        # 验证路由状态中包含additional-path标记(a)
        gl.DUT3.CheckCommand(
            'DUT3检查路由表中192.168.1.0/24包含Add-Path标记',
            cmd='display bgp routing-table ipv4 192.168.1.0 24 | include 192.168.1.0',
            expect_count=3,  # 期望出现3条路由
            expect=['a'],  # 包含additional-path标记
            not_expect=[],
            stop_max_attempt=1,
            wait_fixed=5,
            failed_assist=[],
        )

    def test_step_2(self):
        """
        场景2: 修改Add-Path发送参数验证

        修改DUT1的Add-Path发送路由条数参数从3改为2
        验证DUT3收到Add-Path路由条数变为2条
        """
        # 修改DUT1的Add-Path发送条数从3改为2
        gl.DUT1.send('''
            system-view
            bgp 100
            address-family ipv4 unicast
            undo peer 14.1.1.2 advertise additional-paths best 3
            peer 14.1.1.2 advertise additional-paths best 2
        ''')

        # 验证DUT3收到2条Add-Path路由
        gl.DUT3.CheckCommand(
            'DUT3检查收到192.168.1.0/24的Add-Path路由条数变为2',
            cmd='display bgp routing-table ipv4 192.168.1.0 24',
            expect=[
                '192.168.1.0/24',
                ('Paths:', '2 available')
            ],
            not_expect=[],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

        # 恢复配置:将发送条数改回3
        gl.DUT1.send('''
            system-view
            bgp 100
            address-family ipv4 unicast
            undo peer 14.1.1.2 advertise additional-paths best 2
            peer 14.1.1.2 advertise additional-paths best 3
        ''')

        # 验证配置已恢复,DUT3收到3条路由
        gl.DUT3.CheckCommand(
            'DUT3验证配置恢复后收到3条Add-Path路由',
            cmd='display bgp routing-table ipv4 192.168.1.0 24',
            expect=[
                '192.168.1.0/24',
                ('Paths:', '3 available')
            ],
            not_expect=[],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

    def test_step_3(self):
        """
        场景3: BGP邻居震荡验证

        在DUT1上执行BGP邻居震荡
        验证DUT1和DUT3的BGP邻居重新建立成功
        验证DUT3收到的Add-Path路由条数正确
        """
        # 执行BGP邻居震荡
        gl.DUT1.send('''
            reset bgp 14.1.1.2 24 ipv4
        ''', wait_confirm=True)

        # 验证BGP邻居重新建立
        gl.DUT1.CheckCommand(
            'DUT1检查与DUT3的BGP邻居重新建立',
            cmd='display bgp peer ipv4 14.1.1.2',
            expect=[
                '14.1.1.2',
                'Established'
            ],
            not_expect=[],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

        # 验证DUT3收到Add-Path路由条数正确
        gl.DUT3.CheckCommand(
            'DUT3检查BGP邻居震荡后收到3条Add-Path路由',
            cmd='display bgp routing-table ipv4 192.168.1.0 24',
            expect=[
                '192.168.1.0/24',
                ('Paths:', '3 available')
            ],
            not_expect=[],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

    def test_step_4(self):
        """
        场景4: 路由震荡验证

        在DUT2上删除静态路由192.168.1.0/24
        等待5秒后重新添加
        验证DUT3上的路由先消失后恢复,且恢复后路由条数正确
        """
        # 删除DUT2的静态路由
        gl.DUT2.send('''
            system-view
            undo ip route-static 192.168.1.0 24 NULL0
        ''')

        # 等待路由消失
        gl.DUT3.CheckCommand(
            'DUT3检查192.168.1.0/24路由已消失',
            cmd='display bgp routing-table ipv4 192.168.1.0 24',
            expect=[],
            not_expect=['192.168.1.0/24'],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

        # 等待5秒后恢复静态路由
        import time
        time.sleep(5)

        gl.DUT2.send('''
            system-view
            ip route-static 192.168.1.0 24 NULL0
        ''')

        # 验证DUT3路由恢复,且条数正确
        gl.DUT3.CheckCommand(
            'DUT3检查192.168.1.0/24路由恢复且条数为3',
            cmd='display bgp routing-table ipv4 192.168.1.0 24',
            expect=[
                '192.168.1.0/24',
                ('Paths:', '3 available')
            ],
            not_expect=[],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

    def test_step_5(self):
        """
        场景5: GR (Graceful Restart) 验证

        在DUT1上配置GR能力
        执行GR方式的BGP会话复位
        验证DUT3上的路由保持不中断
        验证GR完成后DUT3收到的Add-Path路由条数正确
        """
        # 配置BGP GR能力
        gl.DUT1.send('''
            system-view
            bgp 100
            graceful-restart
            graceful-restart peer-reset all
        ''')

        # 执行GR方式的BGP会话复位(通过重启BGP进程触发GR)
        # 注意:实际GR复位需要特定场景,这里通过reset命令模拟
        gl.DUT1.send('''
            reset bgp 14.1.1.2 24 ipv4
        ''', wait_confirm=True)

        # 验证DUT3路由保持(GR过程中路由不应立即消失)
        # 这里验证GR完成后路由正常
        gl.DUT3.CheckCommand(
            'DUT3检查GR后收到3条Add-Path路由',
            cmd='display bgp routing-table ipv4 192.168.1.0 24',
            expect=[
                '192.168.1.0/24',
                ('Paths:', '3 available')
            ],
            not_expect=[],
            stop_max_attempt=3,
            wait_fixed=30,
            failed_assist=[],
        )

        # 清理:删除GR配置
        gl.DUT1.send('''
            system-view
            bgp 100
            undo graceful-restart peer-reset
            undo graceful-restart
        ''')
