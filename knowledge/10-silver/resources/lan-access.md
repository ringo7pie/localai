# lan-access

他の PC からこの機体のサービスへ届くかどうかを決めている設定。ポート配置そのものは
`knowledge/10-silver/areas/web-services.md` を Read する。

## ufw は有効で、既定は拒否

- **`ufw` が有効で、既定の方針は `deny (incoming)`。** 明示的に開けたポートだけが LAN から届く。
- **LAN は 2 つある。`<lan-cidr-1>` と `<lan-cidr-2>`（それぞれサブネットのネットワーク表記。例: 192.168.1.0/24 と 192.168.2.0/24）。** ルールは必ず両方に入れる。
  片方だけだと、もう一方のセグメントの PC から使えない。
- サーバー自身の LAN IP は `<server-ip>`（例: 192.168.1.10）。

現在開いているポート（2026-09-27 時点）:

| ポート | 用途 |
|---|---|
| 22 | SSH |
| 7860 / 7861 | Hunyuan3D / Pixal3D の gradio |
| 8080 / 8081 | 入口ページ / Open WebUI |
| 39396 / 39397 | 別用途 |
| Samba | ファイル共有 |

Ollama（11434）は開けない。`127.0.0.1` でしか待受しておらず、LAN へ出す設計にしていない。

## サービスを足したらポートを開ける

**これを忘れると「サーバー自身からは動くのに他の PC から見えない」状態になる。**
Hunyuan3D（ポート 7860）と Pixal3D（7861）は 2026-09-22 に導入したが、ufw のルールを足していな
かったため、2026-09-25 まで他の PC から一度も使えていなかった。`/etc/ufw/user.rules` の更新日が
サービスの導入日より古いときは、この漏れを疑う。

```bash
sudo ufw allow from <lan-cidr-1> to any port <ポート> proto tcp comment '<サービス名> (LAN)'
sudo ufw allow from <lan-cidr-2> to any port <ポート> proto tcp comment '<サービス名> (LAN)'
```

## 「他の PC から見えない」ときの切り分け

上から順に見る。どこで止まっているかで原因が分かれる。

1. **待受アドレス** — `ss -ltnp | grep :<ポート>` が `0.0.0.0` になっているか。`127.0.0.1` だと
   ufw を開けても届かない。gradio なら `--host 0.0.0.0` を渡しているかを確認する。
2. **ufw のルール** — `sudo ufw status numbered` にそのポートの行が、**両方のサブネット分**あるか。
3. **カーネルに載っているか** — `sudo nft list ruleset | grep 'dport <ポート>'` で確認する。
   行末の `counter packets` が 0 のままなら、まだ一度も LAN から通っていない。
   通っていれば数が増えるので、疎通できたかどうかの証拠になる。
4. **サーバー自身から LAN IP 経由で叩く** — `curl -o /dev/null -w '%{http_code}' http://<server-ip>:<ポート>/`。
   これが通ってなお他の PC から見えないなら、原因はサーバー側ではない。
