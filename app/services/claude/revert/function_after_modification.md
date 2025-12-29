!!!func test_step_3_modify_send_best_to_1
!!device DUT1
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
!!device DUT3
display bgp routing-table ipv4 192.168.1.0 24
(期望显示:192.168.1.0)