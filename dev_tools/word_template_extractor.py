import re
from pathlib import Path

from dev_tools.slpp import slpp

"""
提取 `word_template.lua`，也就是敏感词黑名单。

先克隆 https://github.com/Dimbreath/AzurLaneData 获取解密后的脚本。
然后把文件路径填到这里，例如 `<your_folder>/<server>/sharecfg/word_template.lua`。
服务器列表：en-US、ja-JP、ko-KR、zh-CN、zh-TW。
"""
file = ""
with Path(file).open(encoding="utf-8") as f:
    text = f.read()


def extract(dic: dict, word_list: list[str]) -> int:
    """
    提取敏感词，并返回当前分支的词条数量。
    """
    count = 0
    for raw_word, data in dic.items():
        word = str(raw_word)
        if data.get("this", False):
            new = [*word_list, word]
            new = "".join(new)
            count += 1
            print(new)
        else:
            new = [*word_list, word]
            count += extract(data, word_list=new)
    return count


# CN server
count = 0
for result in re.findall("word_template = (.*?)return", text, re.DOTALL):
    pg = slpp.decode(result)
    count += extract(pg, word_list=[])
# Other server
for result in re.findall(r"uv0\.{0,1}(.*?)end", text, re.DOTALL):
    pg = slpp.decode(f"{{{result}}}")
    count += extract(pg, word_list=[])

print(f"Total count: {count}")
