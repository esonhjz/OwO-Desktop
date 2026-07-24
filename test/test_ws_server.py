import asyncio
import websockets
import json

async def handler(websocket):
    print('[+] 已连接')

    # 预热：提前触发动作加载，不等人看到
    print('[~] 预热动作...')
    await websocket.send(json.dumps({'type': 'motion', 'group': 'TapBody', 'no': 0, 'priority': 3}))
    await asyncio.sleep(1.5)

    # 正式测试
    print('[>] 来回切换动作...')
    for i in range(60):
        no = 0 if i % 2 == 0 else 2
        print(f'  [{i}] TapBody[{no}]')
        await websocket.send(json.dumps({'type': 'motion', 'group': 'TapBody', 'no': no, 'priority': 3}))
        await asyncio.sleep(0.12)
    print('[v] 完成')

async def main():
    async with websockets.serve(handler, '127.0.0.1', 3000):
        print('ws://127.0.0.1:3000')
        await asyncio.Future()

asyncio.run(main())
