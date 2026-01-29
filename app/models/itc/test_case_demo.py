# 如下库必须导入，可根据需要导入其它库
from pytest_atf import *
from pytest_atf.atf_globalvar import globalVar as gl
from .conftest import CVarsAndFuncs

# 脚本对应用例的信息，case_no 必须与用例编号对应，如果对应多个用例，用例编号间用英文逗号分隔
module = ''
case_no = 'xxx'

# 脚本标识，每个标识必须使用 "pytest.mark." 声明，可选
pytestmark = [pytest.mark.FUN, pytest.mark.weight6]

# 测试类
class TestClass:
    '''
    XXX此处为脚本测试目的以及脚本开发责任人，格式参考如下：
    测试目的：模板展示
    作者：zhangsan/12345
    开发时间：2022.10.10
    修改记录：
    '''

    @classmethod
    def setup_class(cls):
        '''
        脚本初始配置
        '''
        pass

    @classmethod
    def teardown_class(cls):
        '''
        清除脚本初始配置
        '''
        pass

    def test_step_1(self):
        '''
        XXX此处为脚本测试步骤1描述
        '''
        pass
