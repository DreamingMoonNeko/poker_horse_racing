from GameMaster import GameMaster

def main():
    gm = GameMaster()
    gm.setup()

    print(f"=== 第 {gm.round} 轮，{gm.current_player()} 的回合 ===")
    print(f"抽牌堆剩余: {len(gm.draw_pile)}")

    for p in gm.players:
        print(f"{p.faction.name}: {p.hand.cards}")

    # 测试抽牌
    gm.draw_cards(gm.current_player(), 2)
    print(f"\n抽牌后 {gm.current_player().faction.name} 手牌: "
          f"{gm.current_player().hand.cards}")

    # 测试阶段推进
    gm.next_phase()
    print(f"当前阶段: {gm.phase.name}")

if __name__ == '__main__':
    main()