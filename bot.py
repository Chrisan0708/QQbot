import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

# 初始化 NoneBot
nonebot.init()

# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# 加载 pyproject.toml 中登记的插件：
# 1) [tool.nonebot.plugins] 里的 pip 插件（nb plugin install 装的）
# 2) [tool.nonebot].plugin_dirs 里的本地插件目录（plugins/）
nonebot.load_from_toml("pyproject.toml")
# 加载 echo 复读插件（内置）
nonebot.load_builtin_plugins("echo")

if __name__ == "__main__":
    nonebot.run()

