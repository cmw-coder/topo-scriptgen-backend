import codecs

# 模拟你的数据流
chunk1 = b'...\x28\xe6\x96\x87\xe4' # 结尾是 '件' 的第1个字节
chunk2 = b'\xbb\xb6\x3a...'       # 开头是 '件' 的后2个字节

decoder = codecs.getincrementaldecoder("utf-8")(errors='strict')

# 解码第一块
text1 = decoder.decode(chunk1, final=False)
print(f"块1解码: {text1}") 
# 输出: ...(文 
# 注意：它暂存了 \xe4，没有报错

# 解码第二块
text2 = decoder.decode(chunk2, final=False)
print(f"块2解码: {text2}") 
# 输出: 件:...
# 注意：它把缓存的 \xe4 和这里的 \xbb\xb6 拼起来了解码