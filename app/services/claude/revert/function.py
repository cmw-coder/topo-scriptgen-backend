from pytest import fixture
from pytest_atf import *
from pytest_atf.atf_globalvar import globalVar as gl

# --------用户修改区 -------------------

# 执行层及使用拓扑文件名称
level = 3
topo = r"default.topox"


# 用于声明脚本共用的变量或方法，不能修改类名。
# 变量或方法都要定义为类属性，不要定义为实例属性。
class CVarsAndFuncs:
    pass


# 不能删除setup/teardown的装饰器
@atf_time_stats("ATFSetupTime")
@atf_adornment
def setup():
    """
    BGP Add-Path测试场景初始化配置

    场景说明:
        DUT1和DUT2使用直连接口建立3个IBGP邻居
        DUT1和DUT3使用直连接口建立1个IBGP邻居
        DUT2引入一条静态路由
        DUT1和DUT3使能Add-Path能力

    组网拓扑:
        default.topox
    """
    # 配置DUT1设备
    gl.DUT1.send(
        f"""
        ctrl+z
        system-view
        # 配置Loopback接口
        interface LoopBack0
        ip address 1.1.1.1 32
        undo ip address
        quit
        # 配置接口IP地址
        interface {gl.DUT1.PORT1.intf}
        ip address 11.1.1.1 24
        quit
        interface {gl.DUT1.PORT2.intf}
        ip address 12.1.1.1 24
        quit
        interface {gl.DUT1.PORT3.intf}
        ip address 13.1.1.1 24
        quit
        interface {gl.DUT1.PORT4.intf}
        ip address 14.1.1.1 24
        quit
        # 配置BGP
        bgp 100
        router-id 1.1.1.1
        # 与DUT2建立3个IBGP邻居
        peer 11.1.1.2 as-number 100
        peer 12.1.1.2 as-number 100
        peer 13.1.1.2 as-number 100
        # 与DUT3建立1个IBGP邻居
        peer 14.1.1.2 as-number 100
        #
        address-family ipv4 unicast
        # 使能与DUT2的3个邻居
        peer 11.1.1.2 enable
        peer 12.1.1.2 enable
        peer 13.1.1.2 enable
        # 使能与DUT3的邻居
        peer 14.1.1.2 enable
        peer 14.1.1.2 reflect-client
        # 配置Add-Path发送能力
        peer 14.1.1.2 additional-paths send
        # 配置Add-Path优选路由的最大条数为3
        additional-paths select-best 3
        # 配置向DUT3发送Add-Path优选路由的最大条数为3
        peer 14.1.1.2 advertise additional-paths best 3
        quit
        quit
    """
    )

    # 配置DUT2设备
    gl.DUT2.send(
        f"""
        ctrl+z
        system-view
        # 配置Loopback接口
        interface LoopBack0
        ip address 2.2.2.2 32
        quit
        # 配置接口IP地址
        interface {gl.DUT2.PORT1.intf}
        ip address 11.1.1.2 24
        quit
        interface {gl.DUT2.PORT2.intf}
        ip address 12.1.1.2 24
        quit
        interface {gl.DUT2.PORT3.intf}
        ip address 13.1.1.2 24
        quit
        # 配置静态路由
        ip route-static 192.168.1.0 24 NULL0
        # 配置BGP
        bgp 100
        router-id 2.2.2.2
        # 与DUT1建立3个IBGP邻居
        peer 11.1.1.1 as-number 100
        peer 12.1.1.1 as-number 100
        peer 13.1.1.1 as-number 100
        #
        address-family ipv4 unicast
        # 使能与DUT1的3个邻居
        peer 11.1.1.1 enable
        peer 12.1.1.1 enable
        peer 13.1.1.1 enable
        # 引入静态路由
        import-route static
        quit
        quit
    """
    )

    # 配置DUT3设备
    gl.DUT3.send(
        f"""
        ctrl+z
        system-view
        # 配置Loopback接口
        interface LoopBack0
        ip address 3.3.3.3 32
        quit
        # 配置接口IP地址
        interface {gl.DUT3.PORT4.intf}
        ip address 14.1.1.2 24
        quit
        # 配置BGP
        bgp 100
        router-id 3.3.3.3
        # 与DUT1建立1个IBGP邻居
        peer 14.1.1.1 as-number 100
        #
        address-family ipv4 unicast
        # 使能与DUT1的邻居
        peer 14.1.1.1 enable
        # 配置Add-Path接收能力
        peer 14.1.1.1 additional-paths receive
        quit
        quit
    """
    )


@atf_time_stats("ATFTeardownTime")
@atf_adornment
def teardown():
    """
    清除BGP Add-Path测试场景配置
    """
    # 清除DUT1配置
    gl.DUT1.send(
        f"""
        ctrl+z
        system-view
        undo bgp 100
        y
        undo interface LoopBack0
        interface {gl.DUT1.PORT1.intf}
        undo ip address
        quit
        interface {gl.DUT1.PORT2.intf}
        undo ip address
        quit
        interface {gl.DUT1.PORT3.intf}
        undo ip address
        quit
        interface {gl.DUT1.PORT4.intf}
        undo ip address
        quit
    """
    )

    # 清除DUT2配置
    gl.DUT2.send(
        f"""
        ctrl+z
        system-view
        undo bgp 100
        y
        undo ip route-static 192.168.1.0 24
        undo interface LoopBack0
        interface {gl.DUT2.PORT1.intf}
        undo ip address
        quit
        interface {gl.DUT2.PORT2.intf}
        undo ip address
        quit
        interface {gl.DUT2.PORT3.intf}
        undo ip address
        quit
    """
    )

    # 清除DUT3配置
    gl.DUT3.send(
        f"""
        ctrl+z
        system-view
        undo bgp 100
        y
        undo interface LoopBack0
        interface {gl.DUT3.PORT4.intf}
        undo ip address
        quit
    """
    )


# ---------END-----------


@fixture(scope="package", autouse=True)
def my_fixture_setup_and_teardown():
    atf_topo_map(topo, level)
    try:
        setup()
        yield
    finally:
        teardown()
        atf_topo_unmap()


@fixture(scope="package")
def VarsAndFuncs():
    return CVarsAndFuncs

    def test_step_3_modify_send_best_to_1(self):
        """
        测试步骤2.2: 修改Add-Path发送条数为1

        场景描述:
            DUT1修改Add-Path发送路由条数参数为1
            验证DUT3上收到Add-Path路由,路由条数正确

        预期结果:
            DUT3收到192.168.1.0/24的Add-Path路由条数为1
            该路由为最佳路由
        """
        # 修改DUT1配置为advertise best 2
        gl.DUT1.send(
            """
            ctrl+z
            system-view
            bgp 100
            address-family ipv4 unicast
            #
            undo peer 14.1.1.2 advertise additional-paths best
            peer 14.1.1.2 advertise additional-paths best 2
            #
            quit
            quit
        """
        )

        # 验证DUT3收到1条路由(最佳路由)
        gl.DUT3.CheckCommand(
            "DUT3验证Add-Path路由条数为1",
            cmd="display bgp routing-table ipv4 192.168.1.0 24",
            expect=["192.168.1.0"],
            not_expect=[],
            stop_max_attempt=5,
            wait_fixed=10,
        )
