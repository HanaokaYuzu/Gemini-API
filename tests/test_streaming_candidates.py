"""
测试流式API对多个candidates的支持

验证修复后的代码能够：
1. 正确解析多个candidates
2. 在StreamChunk.candidates中暴露Candidate对象
3. collect()返回所有candidates
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from gemini_webapi import GeminiClient
from gemini_webapi.constants import Model


async def test_streaming_candidates():
    """测试流式API的candidates支持"""
    
    client = GeminiClient(os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"))
    await client.init()
    
    print("\n" + "="*70)
    print("测试1: 检查StreamChunk中的candidates属性")
    print("="*70 + "\n")
    
    stream = await client.generate_content_stream(
        "What is 2+2?",
        model=Model.G_2_5_FLASH
    )
    
    chunk_count = 0
    final_chunk = None
    
    async for chunk in stream:
        chunk_count += 1
        if chunk.candidates:
            print(f"Chunk {chunk_count}: candidates数量 = {len(chunk.candidates)}")
            for i, candidate in enumerate(chunk.candidates):
                print(f"  Candidate {i}: rcid={candidate.rcid[:20]}... text_len={len(candidate.text)}")
        
        final_chunk = chunk
        if chunk.is_final:
            break
    
    print(f"\n✅ 最终chunk:")
    print(f"   总共 {chunk_count} 个chunks")
    print(f"   Candidates数量: {len(final_chunk.candidates)}")
    
    if final_chunk.candidates:
        for i, candidate in enumerate(final_chunk.candidates):
            print(f"\n   Candidate {i}:")
            print(f"     RCID: {candidate.rcid}")
            print(f"     Text: {candidate.text[:80]}...")
            print(f"     Web images: {len(candidate.web_images)}")
            print(f"     Generated images: {len(candidate.generated_images)}")
    else:
        print("   ⚠️  没有candidates（预期至少有1个）")
    
    print("\n" + "="*70)
    print("测试2: 使用collect()获取所有candidates")
    print("="*70 + "\n")
    
    stream2 = await client.generate_content_stream(
        "Explain quantum computing",
        model=Model.G_2_5_FLASH
    )
    
    output = await stream2.collect()
    
    print(f"✅ collect()结果:")
    print(f"   Metadata: {output.metadata}")
    print(f"   Candidates数量: {len(output.candidates)}")
    print(f"   Chosen index: {output.chosen}")
    
    for i, candidate in enumerate(output.candidates):
        print(f"\n   Candidate {i}:")
        print(f"     RCID: {candidate.rcid}")
        print(f"     Text length: {len(candidate.text)}")
        print(f"     Has thoughts: {candidate.thoughts is not None}")
        print(f"     Web images: {len(candidate.web_images)}")
        print(f"     Generated images: {len(candidate.generated_images)}")
    
    print("\n" + "="*70)
    print("测试3: 对比非流式API的candidates")
    print("="*70 + "\n")
    
    # 非流式
    nonstream_output = await client.generate_content(
        "What is AI?",
        model=Model.G_2_5_FLASH
    )
    
    # 流式
    stream3 = await client.generate_content_stream(
        "What is AI?",
        model=Model.G_2_5_FLASH
    )
    stream_output = await stream3.collect()
    
    print(f"非流式 candidates: {len(nonstream_output.candidates)}")
    print(f"流式   candidates: {len(stream_output.candidates)}")
    
    if len(nonstream_output.candidates) == len(stream_output.candidates):
        print("\n✅ 两者candidates数量一致！")
    else:
        print(f"\n⚠️  数量不一致: 非流式={len(nonstream_output.candidates)}, 流式={len(stream_output.candidates)}")
    
    print("\n" + "="*70)
    print("总结")
    print("="*70 + "\n")
    
    print("✅ StreamChunk.candidates 功能:")
    if final_chunk.candidates:
        print(f"   ✓ 正常工作，返回了 {len(final_chunk.candidates)} 个candidates")
    else:
        print("   ✗ 仍然返回空列表")
    
    print("\n✅ collect() 多candidates支持:")
    if output.candidates:
        print(f"   ✓ 正常工作，返回了 {len(output.candidates)} 个candidates")
    else:
        print("   ✗ 没有返回candidates")
    
    print("\n✅ 与非流式API一致性:")
    if len(nonstream_output.candidates) == len(stream_output.candidates):
        print("   ✓ 完全一致")
    else:
        print("   ✗ 存在差异")
    
    await client.close()


async def main():
    if not os.getenv("SECURE_1PSID"):
        print("\n❌ 请设置环境变量 SECURE_1PSID")
        print("   PowerShell: $env:SECURE_1PSID='value'")
        return
    
    try:
        await test_streaming_candidates()
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
