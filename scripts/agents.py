"""複数のAIに役割を分けて、商品紹介記事を書かせる。

1人のAIに一度に全部書かせると、調べる・決める・書く・直すが混ざって浅くなる。
人間の編集部と同じように役割を分け、前の担当の成果物を次の担当に渡す。

  1. リサーチ担当 … 選ばれた商品の実データを読み、比較の軸と事実を整理する
  2. 企画担当     … 読者像と切り口を決め、商品ごとの役割と記事の構成を決める
  3. ライター     … 企画書どおりに本文を書く
  4. 編集長       … 読みやすさ・判断のしやすさ・表示ルールを審査して直す
  5. 事実確認担当 … 本文の主張が商品データで裏づけられるかを1つずつ確かめる
  6. 校正担当     … 事実確認で指摘された文だけを直す

企画担当とライターには、分析担当（scripts/insights.py）が Search Console の実測値から
まとめた「伸びている記事の特徴」も渡し、書き方に反映させる。

一般的な「AIで記事を量産する」手順と違うのは、リサーチ担当が記憶や推測で
市場を語らず、ブラウザで取得した楽天の実データだけを材料にする点。
AIに「調べて」と頼むと、それらしい数字や口コミを作ってしまうため。

各担当の出力は content/reports/ に保存し、あとから判断の経緯を追えるようにする。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Callable

from . import insights
from . import official as official_mod

# (prompt, system, max_tokens, thinking) -> 応答テキスト
# thinking: None ならモデルの既定（考える処理あり）、False なら考える処理を止める
Complete = Callable[..., str]
# complete(prompt, system, max_tokens, thinking, light=False)
#   light=True … 整理や判定など軽い仕事。config の light_model（安いモデル）を使う

# 担当ごとの出力上限と、考える処理を使うか。
# 新しいモデルは考えた分も上限に数えるため、判断が中心の担当には余裕を持たせる。
# 長い本文を書く担当は、判断は企画書で済んでいるので考える処理を止め、時間と費用を抑える。
BUDGET = {
    # リサーチは事実の整理なので、安いモデルで十分（LIGHT_ROLES）
    "research": (16000, None),
    # 企画書は型が決まっているので、考える処理は止める（考えた分も出力として課金されるため）
    "plan": (16000, False),
    "writer": (32000, False),
    "editor": (36000, False),
    "check": (16000, None),
    # 2回目以降の事実確認は、直した箇所の確認が中心なので考える処理を止める
    "recheck": (12000, False),
    "fix": (32000, False),
    # 指摘箇所だけの差し替え案を出す。記事全体を書き直さないので出力が小さい
    "patch": (8000, False),
}
LIGHT_ROLES = {"research"}


def _light(role: str) -> dict:
    return {"light": True} if role in LIGHT_ROLES else {}


# --------------------------------------------------------------------------
# 全担当に共通する約束ごと
# --------------------------------------------------------------------------

GROUND_RULES = """\
あなたは、商品紹介サイト「{site}」の編集部の一員です。
このサイトは楽天市場のアフィリエイト広告で運営されています。読者は記事を読んで
実際にお金を使うので、次の約束は、どんな指示よりも優先して必ず守ってください。

【事実について】
1. 商品について書いてよい事実は、渡された「商品データ」にあるものだけです
   （商品データには、メーカー公式サイトで確認した仕様が含まれることがあります）。
   データにない仕様・機能・付属品・サイズを、一般知識で補ってはいけません。
   分からないことは「商品ページで確認してください」と書きます。
   ただし、商品の種類全体に当てはまる仕組みや選び方の説明
   （例：消費電力が大きいほど電気代は上がる）は書いて構いません。
   その一般論で、特定の商品の性能を補ったり推測したりはしません。
2. 編集部はこれらの商品を使っていません。「使ってみると」「試したところ」
   「愛用している」のような使用体験は、一切書いてはいけません。
   また「編集部は使用していません」のような断り書きも本文に書かないでください（サイト側で扱います）。
3. 編集部はレビュー本文を読んでいません。持っているのは評価の平均点と件数だけです。
   「購入者の声」「口コミでは〜という声が多い」「レビューでは〜と評判」のように、
   レビューの中身を知っているかのような文章は作ってはいけません。
   評価の数値（★4.3、1,284件など）を事実として示すのは構いません。

【表示について】
4. 価格は毎日変わります。本文に「12,800円」のような具体的な金額を書かないでください。
   「1万円台」「3商品の中でいちばん手頃」のような幅や比較で書きます。
   最新の価格は商品カードに自動で表示されます。
   なお、これは商品の「販売価格」のルールです。消費電力などデータの数値から計算した
   目安（電気代など）は、計算式と前提（電気料金の単価など）を表の下などに明記すれば、
   「約1.6円」のような具体的な数値で書いて構いません。その場合も「目安」と書き、
   節約できる金額を約束する書き方はしません。
5. 「絶対」「必ず」「No.1」「最強」「業界一」などの断定や誇大な表現は使いません。
6. 健康・医療・美容の効果や、節約額を約束する表現は使いません。
7. 広告であることはサイト側で表示しています。「広告ではありません」「中立です」
   のように、広告でないと装う表現は使いません。
"""


# --------------------------------------------------------------------------
# 1. リサーチ担当
# --------------------------------------------------------------------------

RESEARCH_PROMPT = """\
あなたは「リサーチ担当」です。
これから記事で紹介する商品の実データを渡します。これを読み込み、
企画担当とライターが迷わず使える「調査メモ」を作ってください。

■ 記事のキーワード
{keyword}

■ 記事の狙い（編集部のメモ）
{intent}

■ 候補全体の傾向（楽天市場で同じ条件で検索した上位{sampled}件の集計）
{market}

■ 紹介する商品（運営者が候補から選んだもの）
{products}

━━━━━━━━━━━━━━━━━━━━
■ 調査メモに書くこと（6項目すべて）
━━━━━━━━━━━━━━━━━━━━
①【読者の状況】
 キーワードから考えられる読者の状況と、いちばん困っていること。
 これは推測なので、冒頭に「（推測）」と付けてください。

②【比較の軸】
 これらの商品を比べるときに、差が出る項目を3〜5個挙げてください。
 軸ごとに、各商品の値を「商品1：〇〇（商品説明に記載）」の形で並べます。
 記載がない商品は「記載なし」と書き、推測で埋めないこと。

③【商品ごとの事実】
 商品ごとに、次を箇条書きで整理します。
 ・価格の位置（候補全体の中で高いか安いか、選んだ商品の中で何番目か）
 ・評価の平均点とレビュー件数、その意味（件数が多いほど平均点は信頼できる）
 ・送料の条件
 ・商品説明から読み取れる主な仕様と特徴（数値はそのまま引用）
 ・この商品にしかない点、または弱い点

④【価格と評価の傾向】
 候補全体の集計から言えることを2〜3点。高い商品ほど評価が高いか、など。

⑤【記事で断定できないこと】
 データが足りず、記事では言い切れないこと。読者が商品ページで確認すべき点。

⑥【差別化の切り口】
 よくある「おすすめ〇選」記事にはなく、このデータだからこそ言える視点を3つ。

━━━━━━━━━━━━━━━━━━━━
■ 出力のルール
━━━━━━━━━━━━━━━━━━━━
・見出しと箇条書きで、短く正確に。飾った文章は不要です。
・事実には必ず出典（どの商品のどの項目か）を添えてください。
"""


# --------------------------------------------------------------------------
# 2. 企画担当
# --------------------------------------------------------------------------

PLAN_PROMPT = """\
あなたは「企画担当」です。
リサーチ担当の調査メモをもとに、検索から読まれ続け、読者が「これを買えばいいのか」と
納得できる商品紹介記事の企画書を作ってください。

■ 記事のキーワード
{keyword}

■ 紹介する商品（{count}個。番号は変えないこと）
番号は運営者が選んだ順です。先に選んだものほど推したい意向があるかもしれませんが、
1位はデータに基づいて決めてください。
{product_names}

■ リサーチ担当の調査メモ
{research}

■ これまでの記事の成績から分かったこと（分析担当のメモ）
{insights}

■ 同じキーワードで検索上位に出ている記事の分析（競合分析担当のメモ）
{serp}

━━━━━━━━━━━━━━━━━━━━
■ 検索で伸びる記事の基本方針（すべての企画で守る）
━━━━━━━━━━━━━━━━━━━━
・検索した人の「本当に知りたいこと」に、ほかの記事より具体的に、漏れなく答える記事が伸びる。
・答えは冒頭に置く。結論を後ろに引っぱる記事は読まれない。
・見出しだけを拾い読みしても、記事の答えが分かるようにする。
・このサイトにしかない材料（楽天の候補全体の集計、商品データの数値による比較）を必ず使う。
・競合分析がある場合は、上位の記事がそろって扱っている論点をすべて押さえたうえで、
  上位の記事に欠けている論点で差をつける。上位と同じことしか書いていない記事は勝てない。
・分析担当のメモは、確からしさが「低」のうちは仮説として扱い、この基本方針を優先する。

━━━━━━━━━━━━━━━━━━━━
■ 企画書に書くこと（すべて必須）
━━━━━━━━━━━━━━━━━━━━
①【記事のひとこと】
 この記事は一言でいうと何か（30字以内）と、読み終えた読者がどうなっているか。

②【想定読者】
 この記事を読む人を1人、具体的に描写します（年代、暮らし、困っている場面、
 何を不安に思って検索したか）。記事の中で実在の人物のように語ることはしません。
 あくまで書き手が読者を思い浮かべるための設定です。

③【検索した人が知りたいこと】
 このキーワードで検索する人が持っている疑問を、8〜12個書き出します。
 メインの疑問（どれを買えばいいか）だけでなく、その前後の疑問も含めます。
   例）何が違うのか／自分の部屋や机に合うか／手入れや交換の手間は／
       安いものと高いものの差は／買う前に測る・確かめることは何か
 分析担当のメモに「実際に検索された言い方」があれば、近いものを優先して入れます。
 それぞれに「どの節で答えるか」を書き添えてください。答えられない疑問
 （商品データにない性能など）は、「商品ページで確認」と案内する節を決めます。

④【商品の役割分担】
 商品ごとに「〇〇な人に向いている」を1つずつ割り当て、根拠を調査メモから示します。
 役割が重ならないようにしてください。
 そのうえで、迷った人に勧める1位を1つ選び、理由を3点挙げます。
 1位の番号を、行頭に「TOP: 商品番号」の形で1行だけ書いてください（例：TOP: 2）。

⑤【タイトル】
 案を3つ出し、最後に1つ選びます。次の形を基本にします。
   「読者の悩みや疑問（〜？）」＋「この記事で分かること（数字・比べ方）」
   例）掃除機の音は何dB（デシベル）？集合住宅向け静音3台を比較
       大きいマウスパッドがデスクからはみ出す？サイズで選ぶ3選
 ・前半は、検索した人が使う言葉で悩みや疑問を書く（疑問形「〜？」を基本にする）。
   分析担当のメモに「実際に検索された言い方」があれば、それに近い言葉を優先する
 ・後半は、紹介する商品数と、何で比べるか（dB・W数・サイズ・公式仕様など）を書く
 ・32字以内（スマホの検索結果で途中で切れないように）
 ・本文で答えていない疑問は書かない。健康・節約の効果を約束する疑問文にしない
 ・煽りすぎない（「神」「最強」「絶対」は使わない）

⑥【記事の型】
 このサイトの記事が、どれも同じ骨組み・同じ見出しにならないよう、
 キーワードの意図に最も合う型を次の4つから1つ選びます。
 行頭に「TYPE: 型の名前」の形で1行だけ書いてください（例：TYPE: 悩み解決型）。
   ・比較型 ………… 「どれを買えばいいか」で迷っている人向け。結論→比較→商品→選び方の順
   ・悩み解決型 …… 困りごとがはっきりしている人向け（結露・乾燥・音・置けない など）。
                     原因→解決の方向性→それに合う商品→使い方の順
   ・選び方解説型 … 「何を基準に選べばいいか」を知りたい人向け（何dB？何W？どのサイズ？）。
                     基準の説明が主役で、商品は基準の具体例として後半に置く
   ・早見表型 ……… 数字の対応が知りたい人向け（W数と畳数、容量と運転時間、サイズと置き場所）。
                     冒頭に早見表を置き、表の読み方と商品の当てはめを続ける
 競合分析で上位の記事がどの型か、検索した人が③で何を一番知りたいかで決めます。
 理由を1〜2行で添えてください。

⑦【構成と字数の配分】
 ⑥で選んだ型に沿って、見出しと、それぞれで書くこと、目安の字数を決めます。
 本文の合計は5,000〜7,000字にします。字数は③の疑問に答えるために使い、
 同じ話の繰り返しや一般論で埋めないこと。
 ・## と ### の見出しは、この記事のテーマでしか使えない言葉で書きます。
   「迷ったらこれ」「良いところ」「選び方のポイント」「まとめ」のような、
   どの記事にも使える決まり文句の見出しは使わないこと。
   （良い例：「天板4cmを超えるならクランプより補強プレートを先に確認」
             「寝室なら音が30dB台の気化式が候補になる」）
 ・どの型でも、次は必ず入れます（置く順番と見出しの言葉は型と内容に合わせて決める）。
   - リード文（見出しなし）：最初の3文で結論と対象読者を言う
   - 1位の商品を示す節（<!--TOP:n--> を置く）
   - 全商品の比較表の節（<!--COMPARE--> を置く）
   - 商品ごとの節（{count}個。<!--PRODUCT:n--> を置く）。向いている人・良い点・
     気をつけたい点・主な仕様を扱うが、小見出しの言葉は商品と記事に合わせて書く
   - **この記事だけの表**：商品データの数値から作る、他のサイトにない表を1つ
     （例：消費電力から計算した電気代の目安表、容量と連続運転時間の対応表、
      天板の厚さとクランプ対応範囲の表、dB値の並べ替え表）。
     計算に仮定を使うときは、仮定（電気料金の単価など）を表の下に明記する
 ・次は、意味のある内容があるときだけ入れます（毎回入れなくてよい）。
   - 楽天市場の候補全体のデータの節（<!--STATS--> を置く）
   - よくある質問（入れるなら3〜6問。③の疑問から選ぶ）
   - 買う前に確認したいこと、使い方・状況別の当てはめ
 ・節ごとの目安字数も書き添えます。

⑧【企画のまとめ】
 この記事が、同じキーワードのほかの記事に勝てる理由を3行以内で。
"""


# --------------------------------------------------------------------------
# 3. ライター
# --------------------------------------------------------------------------

WRITER_PROMPT = """\
あなたは「ライター」です。
企画書に従って、商品紹介記事の本文を書いてください。

■ 記事のキーワード
{keyword}

■ 企画書
{plan}

■ リサーチ担当の調査メモ（事実はここと商品データから取ること）
{research}

■ 商品データ
{products}

■ これまでの記事の成績から分かったこと（分析担当のメモ）
{insights}

■ 同じキーワードで検索上位に出ている記事の分析（競合分析担当のメモ）
{serp}

━━━━━━━━━━━━━━━━━━━━
■ 検索で伸びる書き方（とても重要）
━━━━━━━━━━━━━━━━━━━━
1. 冒頭3文で答える。リード文の最初で「結論」と「どんな人向けの記事か」を言い切る。
2. 企画書③の「検索した人が知りたいこと」に、すべて答える。
   答えたかどうかを、書き終えたあとに1つずつ確認すること。
3. 情報の密度を上げる。各段落に、商品データの数値・条件・商品どうしの比較の
   いずれかを必ず入れる。「〜は大切です」「〜を確認しましょう」だけの段落は書かない。
4. 仕組みや背景（なぜ結露するのか、なぜ天板の厚みが問題になるのか など）の説明は
   読者の判断を助けるので書いてよい。ただし一般的な説明にとどめ、
   特定の商品の性能や効果として書かないこと（商品について書けるのは商品データだけ）。
5. 企画書⑥の「記事の型」と⑦の構成に従う。見出しは企画書の言葉を使い、
   「迷ったらこれ」「良いところ」「選び方のポイント」「まとめ」のような
   どの記事にも使える決まり文句の見出しにしない。
6. 企画書で決めた「この記事だけの表」を、Markdownの表で必ず入れる。
   数値は商品データから取り、計算したものは計算方法と仮定を表の下に書く。
7. よくある質問を入れる場合は ### Q. で始め、質問文は検索で使われる言い方にする。
   答えの1文目で結論を言い、2文目以降で根拠や条件を足す。
8. 分析担当のメモにある指示を取り入れる。ただし、確からしさが「低」のときは
   上の1〜7を優先する。

━━━━━━━━━━━━━━━━━━━━
■ 読みやすさ
━━━━━━━━━━━━━━━━━━━━
このサイトの読者はスマホで、急いで読みます。文字が詰まったページは読まれません。
・1段落は2〜3文まで。1文は60字くらいまで。
・商品ごとの節では、向いている人・良い点・気をつけたい点・主な仕様を扱います。
  小見出しは毎回その商品に合わせて書き（例：「### 6畳までの寝室なら音の小ささが活きる」
  「### タンクが小さいぶん給水の回数は増える」）、箇条書きと1〜2段落の説明で
  「なぜそう言えるか」まで書きます。
・大事な一文は **太字** にします。多用はしないこと（1セクションに1〜2か所）。
・補足や注意は、行頭を「> 」にした囲み（引用）にします。
    例）> **ポイント**：幅は商品ページの「サイズ」欄で確認できます。
・良い点だけでなく、必ず気をつけたい点も書きます。
  短所がない商品はありません。読者の信頼はここで決まります。

━━━━━━━━━━━━━━━━━━━━
■ 文体
━━━━━━━━━━━━━━━━━━━━
・です・ます調。詳しい友人が説明してくれるような、落ち着いた温度感。
・同じ語尾を3回続けない。「〜することが重要です」「〜が不可欠です」を多用しない。
・「いかがでしたか」「さあ、〜しましょう」「ここで大切なことをお伝えします」は使わない。
・専門用語は、初めて出てくるときに短く言い換える。

━━━━━━━━━━━━━━━━━━━━
■ 差し込み位置（この記号を、そのまま1行で書くこと）
━━━━━━━━━━━━━━━━━━━━
・<!--TOP:n-->     … 1位の商品を示す節の見出しの直後に1回。nは1位の商品番号。1位の商品カードが入る
・<!--COMPARE-->   … 比較表の見出しの直後に1回。全商品の比較表が入る
・<!--PRODUCT:n--> … 商品ごとの見出しの直後に1回ずつ。その商品のカードが入る
・<!--STATS-->     … 楽天市場の候補全体のデータの節を作った場合だけ、その見出しの直後に1回。
                      集計が入る。節を作らないなら書かない
カードには商品名・画像・最新価格・評価・購入ボタンが自動で入ります。
本文で同じ情報を繰り返す必要はありません。

━━━━━━━━━━━━━━━━━━━━
■ 分量と出力形式
━━━━━━━━━━━━━━━━━━━━
・本文は全体で5,000〜7,000字。企画書⑦の節ごとの目安字数に合わせる。
  目安に届かない節は、商品データの仕様・数値・条件を使った具体例で厚くする。
  言い換え・繰り返し・一般論で字数を埋めることはしない。
・1行目に「TITLE: 」に続けて企画書で選んだタイトル（32字以内）。
・2行目に「DESC: 」に続けて検索結果に出る説明文（100〜120字。キーワードの主要な語と、
  この記事で分かることを入れる）。
・3行目以降に本文（Markdown）。見出しは ## と ### を使い、# は使わない。
"""


# --------------------------------------------------------------------------
# 4. 編集長
# --------------------------------------------------------------------------

EDITOR_PROMPT = """\
あなたは「編集長」です。商品紹介記事を何百本も見てきたベテランです。
ライターの原稿を審査し、そのまま公開できる完成版に仕上げてください。

■ 記事のキーワード
{keyword}

■ 商品データ（事実の照合に使う）
{products}

■ 企画書（狙いからズレていないかの確認に使う）
{plan}
{extra}
■ 原稿
{draft}

━━━━━━━━━━━━━━━━━━━━
■ 審査の観点（7つ）
━━━━━━━━━━━━━━━━━━━━
【1. AIっぽさ】
 定番の言い回し、同じ語尾の連続、「まず〜次に〜最後に」の型どおりの並べ方、
 意味のない前置き、誰にでも当てはまるふわっとした表現を、人の言葉に直す。

【2. 読者の迷いが解けるか】
 結論が冒頭近くにあるか。商品ごとの「向いている人」が重ならず、はっきりしているか。
 比較の軸が記事の最初から最後まで一貫しているか。

【3. 買う判断ができるか】
 各商品に、良い点と気をつけたい点の両方があるか。
 購入ボタンの前に、判断に必要な材料がそろっているか。

【4. 文章の質】
 誤字脱字、不自然な日本語、長すぎる文、近い場所での言い回しの重複、
 見出しと本文のズレ。スマホで詰まって見える段落は分ける。

【5. 事実と表示のルール】
 商品データにない仕様、使用体験、レビューの中身を知っているような表現、
 具体的な金額、誇大な表現がないか。見つけたら削るか、データに基づく表現に直す。
 差し込み記号（<!--TOP:n--> <!--COMPARE--> <!--PRODUCT:n--> <!--STATS-->）が
 正しい位置に1回ずつあるかも確認する。

【6. 量産記事に見えないか】
 企画書の「記事の型」に沿っているか。「迷ったらこれ」「良いところ」「選び方のポイント」
 「まとめ」のような、どの記事にも使える決まり文句の見出しが残っていたら、
 その記事の内容に合わせた見出しに書き換える。「この記事だけの表」が入っているか。

【7. 検索で伸びるか】
 リード文の最初の3文で結論と対象読者が分かるか。
 企画書③の「検索した人が知りたいこと」にすべて答えているか。答えていない疑問があれば、
 該当する節に商品データに基づく答えを足す。
 ## の見出しが、検索した人の言い方を含む「答えが分かる見出し」になっているか。
 本文が5,000字に届かない場合は、目安字数より薄い節を、商品データの数値・条件を使って
 厚くする（一般論や言い換えで埋めない）。

━━━━━━━━━━━━━━━━━━━━
■ 出力の形式（この順番で）
━━━━━━━━━━━━━━━━━━━━
REPORT:
（直した点を、全部で5行以内の箇条書きで。各行40字程度まで）
===ARTICLE===
TITLE: （タイトル）
DESC: （説明文）
（完成した本文の全文。省略せずに最後まで）
"""


# --------------------------------------------------------------------------
# 5. 事実確認担当
# --------------------------------------------------------------------------

CHECK_PROMPT = """\
あなたは「事実確認担当」です。公開直前の記事を、商品データと1文ずつ突き合わせます。
読みやすさや表現の好みは見ません。見るのは「事実として正しいか」と「ルール違反か」だけです。

■ 商品データ
{products}

■ 候補全体の集計データ（記事で使ってよい材料。ここにある数値は裏づけありとして扱う）
{market}

■ 記事
{article}

━━━━━━━━━━━━━━━━━━━━
■ 確認すること
━━━━━━━━━━━━━━━━━━━━
1. 商品の仕様・機能・数値の記述が、その番号の商品データで裏づけられるか
   （商品2の紹介に商品3の仕様が書かれていないか、も含む）
2. 使用体験を書いていないか
3. レビューの中身を知っているかのような記述がないか
4. 商品の販売価格を具体的な金額で書いていないか（「1万円台」のような幅は可）。
   データの数値から計算した目安（電気代など）は、計算式と前提が明記されていれば問題にしない。
   その場合は、計算が商品データの数値と前提から正しく出せるかだけを確かめる
5. 「絶対」「必ず」「No.1」などの断定・誇大な表現、効果の約束がないか
   （「必ずしも〜ない」は断定ではないので問題にしない）

━━━━━━━━━━━━━━━━━━━━
■ 出力（JSONのみ。説明文やコードブロックの記号は付けない）
━━━━━━━━━━━━━━━━━━━━
{{"ok": true または false,
  "issues": [
    {{"level": "重大" または "軽微",
      "quote": "記事の該当箇所をそのまま抜き出す（1文以内）",
      "problem": "何が問題か（短く）",
      "fix": "どう直すか（短く）"}}
  ]}}
問題がなければ {{"ok": true, "issues": []}} だけを返します。
・level の決め方
  重大：商品データと食い違う数値・仕様・順位・比較、別の商品の仕様の混入、使用体験、
        レビューの中身を知っているかのような記述、販売価格の具体的な金額、
        「必ず治る」「〇円節約できる」のような効果や節約額の断定
  軽微：それ以外（言い回しの好み、推測の度合い、念のための注意）
・自分で「問題ない」「修正不要」と判断した箇所は、issues に入れないでください。
・JSONの文字列の中で " を使うときは \\" と書きます。
一般的な知識として正しいことでも、商品データにない商品固有の主張は問題として挙げてください。
商品の種類全体についての一般的な仕組みの説明は、特定の商品に当てはめていなければ問題にしません。
価格の順位や「いちばん手頃」のような比較は、渡された商品データの価格と合っていれば問題にしません。
"""


FIX_PROMPT = """\
あなたは「校正担当」です。事実確認で指摘された箇所だけを直します。

■ 商品データ
{products}

■ 候補全体の集計データ
{market}

■ 指摘（すべて直すこと）
{problems}

■ 記事
{article}

━━━━━━━━━━━━━━━━━━━━
■ 直し方
━━━━━━━━━━━━━━━━━━━━
・指摘された文だけを、指摘の「→」に沿って最小限に書き換える。
・指摘のない文、見出し、表、<!--...--> の印は一字も変えない。
・字数を増やさない。新しい説明を書き足さない。
・裏づけのない内容は、言い換えるより削る。
・本文が短いという指摘には、商品データにある仕様の説明を足して対応する（一般論は足さない）。

■ 出力
1行目に「TITLE: 」、2行目に「DESC: 」、3行目から本文（元の記事と同じ形式）。説明文は付けない。
"""


PATCH_PROMPT = """\
あなたは「校正担当」です。事実確認で指摘された箇所だけを直します。
記事全体は書き直さず、直す文の「差し替え案」だけを出してください。

■ 候補全体の集計データ
{market}

■ 指摘（すべて直すこと）
{problems}

■ 記事
{article}

━━━━━━━━━━━━━━━━━━━━
■ 直し方
━━━━━━━━━━━━━━━━━━━━
・old には、記事の中の直したい部分を、一字一句そのまま写す（1文か、文の一部）。
  記事の中で1か所にしか出てこない長さにすること。
・new には、指摘の「→」に沿って最小限に直した文を書く。削るだけなら空文字。
・裏づけのない内容は、言い換えるより削る。新しい説明を書き足さない。
・<!--...--> の印は消さない・動かさない。

■ 出力（JSONのみ）
{{"edits": [{{"old": "記事の中の文をそのまま", "new": "直した文"}}]}}
"""


def apply_edits(title: str, desc: str, body: str, text: str,
                log=print) -> tuple[str, str, str, int]:
    """差し替え案を適用する。old が1か所にだけ見つかるものだけを使う。"""
    start, end = text.find("{"), text.rfind("}")
    try:
        edits = json.loads(text[start:end + 1]).get("edits") or []
    except (ValueError, AttributeError):
        return title, desc, body, 0
    applied = 0
    for e in edits:
        if not isinstance(e, dict):
            continue
        old, new = str(e.get("old") or ""), str(e.get("new") or "")
        if len(old) < 4 or "<!--" in old and "<!--" not in new:
            continue
        if title.count(old) == 1:
            title = title.replace(old, new); applied += 1
        elif desc.count(old) == 1:
            desc = desc.replace(old, new); applied += 1
        elif body.count(old) == 1:
            body = body.replace(old, new); applied += 1
        else:
            log(f"        差し替え先が見つからないため飛ばしました：{old[:40]}")
    return title, desc, body, applied


# --------------------------------------------------------------------------
# 機械的な検査（AIに頼らず確実に見られるもの）
# --------------------------------------------------------------------------

EXPERIENCE_WORDS = [
    "実際に使って", "使ってみると", "使ってみて", "試してみ", "筆者", "私が使",
    "愛用し", "購入して", "使い始めて", "使い続けてい", "使い続けてき", "手に取って", "届いてすぐ",
]
REVIEW_WORDS = [
    "購入者の声", "口コミでは", "口コミによると", "レビューでは", "レビューによると",
    "という声", "との声", "利用者からは", "評判です", "と好評",
]
# どの記事にも使える決まり文句の見出し。量産記事に見えるので使わない
STOCK_HEADINGS = {
    "迷ったらこれ", "結論：迷ったらこれ", "比較表", "良いところ", "気をつけたいところ",
    "こんな人に向いています", "商品説明から分かる主な仕様", "選び方のポイント",
    "買う前に確認したいこと", "楽天市場のデータから分かること", "よくある質問", "まとめ",
    "使い方・状況別のおすすめ",
}

# 体裁の指摘。校正担当に直させるが、直しきれなくても公開は止めない
# （誤りではないので、人の確認に回すほどではない）
STYLE = "【体裁】"

# 本文の最低字数。目安は5,000〜7,000字。これを下回ったら校正担当が商品データで厚くする
MIN_CHARS = 4000
HYPE_WORDS = ["絶対", "必ず", "No.1", "ナンバーワン", "最強", "業界一", "日本一"]
# 「3,000円台」「1万円前後」のような幅は許し、ぴったりの金額だけを拾う
EXACT_PRICE = re.compile(
    r"(?:\d{1,3}(?:,\d{3})+|\d{4,})円(?!台|前後|以下|以上|未満|程度|くらい|ほど|帯|〜|~)")


def drop_sentences(body: str, quotes: list[str]) -> tuple[str, int]:
    """指摘された文を、その文を含む「。」までの1文ごと本文から削る。

    見出し・表・差し込み記号を含む行は削らない（記事の形が崩れるため）。
    削れた数を返す。全部削れなかった場合は、呼び出し側で公開を止めたままにする。
    """
    removed = 0
    for quote in quotes:
        q = quote.strip().strip("「」…").split("…")[0].strip()
        if len(q) < 8 or body.count(q) != 1:
            continue
        start = body.index(q)
        line_start = body.rfind("\n", 0, start) + 1
        line_end = body.find("\n", start)
        line_end = len(body) if line_end < 0 else line_end
        line = body[line_start:line_end]
        if line.lstrip().startswith(("#", "|", "<!--")) or "<!--" in line:
            continue
        s = max(body.rfind("。", line_start, start) + 1, line_start)
        e = body.find("。", start)
        if e < 0 or e >= line_end:
            e = line_end - 1
        body = body[:s] + body[e + 1:]
        removed += 1
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body, removed


def lint(body: str, count: int, top: int) -> list[str]:
    """公開してはいけない原稿を機械的に見つける。問題を文章で返す。"""
    issues = []
    for n in range(1, count + 1):
        c = body.count(f"<!--PRODUCT:{n}-->")
        if c != 1:
            issues.append(f"<!--PRODUCT:{n}--> が{c}回あります（1回だけにする）")
    c = body.count("<!--COMPARE-->")
    if c != 1:
        issues.append(f"<!--COMPARE--> が{c}回あります（1回だけにする）")
    c = body.count("<!--STATS-->")
    if c > 1:
        issues.append(f"<!--STATS--> が{c}回あります（使うなら1回だけにする）")
    stock = [h for h in re.findall(r"^#{2,3} (.+)$", body, flags=re.MULTILINE)
             if h.strip() in STOCK_HEADINGS]
    if stock:
        issues.append(STYLE + "どの記事にも使える決まり文句の見出しがあります："
                      + "、".join(sorted(set(stock))) + "（記事の内容に合わせた見出しにする）")
    if not re.search(r"^\|.+\|\s*$\n^\|\s*:?-{2,}", body, flags=re.MULTILINE):
        issues.append(STYLE + "この記事だけの表（商品データの数値から作るMarkdownの表）がありません")
    tops = re.findall(r"<!--TOP:(\d+)-->", body)
    if len(tops) != 1:
        issues.append(f"<!--TOP:n--> が{len(tops)}回あります（1回だけにする）")
    elif not 1 <= int(tops[0]) <= count:
        issues.append(f"<!--TOP:{tops[0]}--> の番号が商品の範囲外です")

    chars = len(re.sub(r"<!--.*?-->|\s", "", body))
    if chars < MIN_CHARS:
        issues.append(f"本文が{chars}字しかありません（{MIN_CHARS:,}字以上にする）")

    for label, words in (("使用体験", EXPERIENCE_WORDS), ("レビューの中身", REVIEW_WORDS),
                         ("誇大な表現", HYPE_WORDS)):
        text = body.replace("必ずしも", "")      # 「必ずしも〜ない」は断定ではない
        found = [w for w in words if w in text]
        if found:
            issues.append(f"{label}を示す表現があります：{'、'.join(found)}")
    prices = EXACT_PRICE.findall(body)
    if prices:
        issues.append(f"具体的な金額があります：{'、'.join(sorted(set(prices))[:5])}"
                      "（幅や比較の表現に直す）")
    if re.search(r"^# ", body, flags=re.MULTILINE):
        issues.append("見出しに # が使われています（## と ### だけにする）")
    return issues


# --------------------------------------------------------------------------
# 材料の整形
# --------------------------------------------------------------------------

def yen(n) -> str:
    try:
        return f"{int(n):,}円"
    except (TypeError, ValueError):
        return "不明"


def describe_products(products: list[dict], official: dict | None = None) -> str:
    blocks = []
    for i, p in enumerate(products, 1):
        extra = official_mod.describe(official or {}, i)
        rating = p.get("reviewAverage") or 0
        count = p.get("reviewCount") or 0
        blocks.append("\n".join([
            f"[商品{i}]",
            f"商品名: {p.get('itemName', '')}",
            f"価格: {yen(p.get('itemPrice'))}（{p.get('capturedAt', '取得日不明')}時点。毎日変わるので本文には書かない）",
            f"評価: {float(rating):.2f}（レビュー{int(count):,}件）" if count else "評価: レビューなし",
            f"送料: {'無料' if p.get('postageFlag') == 0 else '別（条件は商品ページ）'}",
            f"ショップ: {p.get('shopName', '')}",
            f"キャッチコピー: {p.get('catchcopy', '') or '（なし）'}",
            "商品説明（ショップの記載・抜粋）:",
            p.get("itemCaption", "") or "（なし）",
        ] + ([extra] if extra else [])))
    return "\n\n".join(blocks)


def describe_market(market: dict) -> str:
    if not market:
        return "（集計なし）"
    lines = []
    if market.get("total"):
        lines.append(f"・検索結果の総数：{int(market['total']):,}件")
    if market.get("priceMedian"):
        lines.append(f"・価格の中央値：{yen(market['priceMedian'])}"
                     f"（最安 {yen(market.get('priceMin'))} ／ 最高 {yen(market.get('priceMax'))}）")
    if market.get("ratingAverage"):
        lines.append(f"・評価の平均：{float(market['ratingAverage']):.2f}")
    if market.get("freeShippingRate") is not None:
        lines.append(f"・送料無料の割合：{round(float(market['freeShippingRate']) * 100)}%")
    return "\n".join(lines) or "（集計なし）"


def product_names(products: list[dict]) -> str:
    return "\n".join(f"商品{i}：{p.get('itemName', '')[:60]}" for i, p in enumerate(products, 1))


def parse_article(text: str) -> tuple[str, str, str]:
    """「TITLE: / DESC: / 本文」を分解する。前後に余計な行があっても拾う。"""
    title = desc = ""
    lines = text.strip().splitlines()
    body_start = 0
    for i, line in enumerate(lines[:6]):
        if line.startswith("TITLE:"):
            title, body_start = line[6:].strip(), i + 1
        elif line.startswith("DESC:"):
            desc, body_start = line[5:].strip(), i + 1
    return title, desc, "\n".join(lines[body_start:]).strip()


def parse_top(plan: str, count: int) -> int:
    m = re.search(r"TOP:\s*(?:商品)?\s*(\d+)", plan)
    if m and 1 <= int(m.group(1)) <= count:
        return int(m.group(1))
    return 1


def parse_check(text: str) -> dict:
    """事実確認担当のJSONを読む。壊れていたら「確認できなかった」扱いにする。"""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    try:
        data = json.loads(cleaned[start:end + 1])
        found = [i for i in data.get("issues", []) if isinstance(i, dict)]
        # 軽微な指摘は記録に残すだけで、直させたり公開を止めたりしない
        # （確認のたびに新しい細かい指摘が出て、いつまでも公開できなくなるため）
        issues = [i for i in found if "軽微" not in str(i.get("level", ""))]
        minor = [i for i in found if "軽微" in str(i.get("level", ""))]
        return {"ok": not issues, "issues": issues, "minor": minor}
    except (ValueError, AttributeError):
        return {"ok": False, "unreadable": True,
                "issues": [{"quote": "", "problem": "事実確認の結果を読み取れませんでした",
                            "fix": "人が確認する"}]}


# --------------------------------------------------------------------------
# 本体
# --------------------------------------------------------------------------

@dataclass
class Result:
    title: str
    description: str
    body: str
    top: int
    ok: bool                                   # 公開してよいか
    issues: list[str] = field(default_factory=list)
    reports: dict = field(default_factory=dict)


def write_article(entry: dict, products: list[dict], market: dict,
                  config: dict, complete: Complete, log=print,
                  official: dict | None = None, serp_text: str = "") -> Result:
    """5つの担当を順に動かして記事を仕上げる。"""
    keyword = entry["keyword"]
    intent = entry.get("intent") or f"{keyword}で探している読者が、自分に合う商品を選べるようにする"
    # 商品データは全担当が使う。毎回の依頼文に埋め込まず、共通の前置き（system）に1回だけ置き、
    # APIのキャッシュで2回目以降の読み込みを安くする
    system = (GROUND_RULES.format(site=config.get("site_title", "当サイト"))
              + "\n\n━━━━━━━━━━━━━━━━━━━━\n■ この記事で扱う商品データ（全担当共通）\n"
              "━━━━━━━━━━━━━━━━━━━━\n" + describe_products(products, official))
    facts = "（前置きの「この記事で扱う商品データ」を参照してください）"
    count = len(products)
    reports: dict = {}
    serp_text = serp_text or "（今回は競合の分析がありません。基本方針どおりに企画してください）"

    log("  [1/5] リサーチ担当が商品データを整理しています")
    research = complete(RESEARCH_PROMPT.format(
        keyword=keyword, intent=intent, market=describe_market(market),
        sampled=market.get("sampled", "数十"), products=facts), system, *BUDGET["research"],
        **_light("research"))
    reports["research"] = research

    log("  [2/5] 企画担当が構成を決めています")
    plan = complete(PLAN_PROMPT.format(
        keyword=keyword, count=count, product_names=product_names(products),
        research=research, insights=insights.for_prompt("plan"),
        serp=serp_text), system, *BUDGET["plan"])
    reports["plan"] = plan
    top = parse_top(plan, count)

    log("  [3/5] ライターが本文を書いています")
    draft = complete(WRITER_PROMPT.format(
        keyword=keyword, plan=plan, research=research, products=facts,
        insights=insights.for_prompt("writer"), serp=serp_text), system, *BUDGET["writer"])
    reports["draft"] = draft

    def edit(text: str, extra: str = "") -> tuple[str, str, str, str]:
        out = complete(EDITOR_PROMPT.format(
            keyword=keyword, products=facts, plan=plan, draft=text,
            extra=extra), system, *BUDGET["editor"])
        report, _, article = out.partition("===ARTICLE===")
        if not article.strip():                  # 区切りを書き忘れた場合
            report, article = "", out
        title, desc, body = parse_article(article)
        return report.replace("REPORT:", "").strip(), title, desc, body

    log("  [4/5] 編集長が審査して直しています")
    report, title, desc, body = edit(draft)
    reports["edit"] = report

    # 事実確認と機械検査。問題があれば校正担当が指摘箇所だけを直し、最大3回まで確認する
    # （記事全体を書き直すと、直した以外の場所に新しい誤りが入りやすいため）
    market_text = describe_market(market)
    problems: list[str] = []
    for attempt in (1, 2, 3):
        log(f"  [5/5] 事実確認担当が確認しています（{attempt}回目）")
        try:
            prompt = CHECK_PROMPT.format(products=facts, market=market_text,
                                         article=f"TITLE: {title}\n\n{body}")
            budget = BUDGET["check" if attempt == 1 else "recheck"]
            checked = parse_check(complete(prompt, system, *budget))
            if checked.get("unreadable"):
                log("        確認結果を読み取れなかったので、もう一度確認します")
                checked = parse_check(complete(prompt, system, *budget))
        except RuntimeError as exc:
            # 確認できなかった記事は公開しない。ただし書き上げた原稿は捨てず、承認待ちに回す
            log(f"        事実確認を実行できませんでした: {exc}")
            problems = lint(body, count, top) + [f"事実確認を実行できませんでした（{exc}）"]
            reports[f"check_{attempt}"] = {"error": str(exc), "lint": lint(body, count, top)}
            break
        problems = lint(body, count, top) + [
            f"「{i.get('quote', '')[:60]}」… {i.get('problem', '')}（→ {i.get('fix', '')}）"
            for i in checked["issues"]]
        reports[f"check_{attempt}"] = {"ai": checked, "lint": lint(body, count, top)}
        if not problems or attempt == 3:
            break
        log(f"        問題が{len(problems)}件あったので校正担当が直します")
        # 字数不足以外は、指摘箇所の差し替えだけで直す（出力が小さく、ほかの箇所も壊さない）
        if not any("字しかありません" in p for p in problems):
            try:
                out = complete(PATCH_PROMPT.format(
                    market=market_text, problems="\n".join(f"- {p}" for p in problems),
                    article=f"TITLE: {title}\nDESC: {desc}\n{body}"), system, *BUDGET["patch"])
                title, desc, body, n = apply_edits(title, desc, body, out, log)
                reports[f"fix_{attempt}"] = out
                log(f"        {n}か所を差し替えました")
                continue
            except RuntimeError as exc:
                log(f"        差し替えに失敗したので、全体の修正に切り替えます: {exc}")
        try:
            fixed = complete(FIX_PROMPT.format(
                products=facts, market=market_text,
                problems="\n".join(f"- {p}" for p in problems),
                article=f"TITLE: {title}\nDESC: {desc}\n{body}"), system, *BUDGET["fix"])
        except RuntimeError as exc:
            log(f"        修正に失敗しました: {exc}")
            problems.append(f"修正に失敗しました（{exc}）")
            break
        t2, d2, b2 = parse_article(fixed)
        reports[f"fix_{attempt}"] = fixed
        if b2:
            title, desc, body = t2 or title, d2 or desc, b2

    # 3回直しても指摘が残った文は、文ごと削る（APIを使わない）。
    # 削っても新しい誤りは入らないので、残りが体裁の指摘だけになれば公開してよい
    failed = any("できませんでした" in p or "失敗しました" in p for p in problems)
    if problems and not failed and "checked" in locals() and checked.get("issues"):
        body, removed = drop_sentences(body, [i.get("quote", "") for i in checked["issues"]])
        if removed == len(checked["issues"]):
            log(f"        直しきれなかった{removed}文を削りました")
            problems = lint(body, count, top)
            reports["dropped_sentences"] = removed

    # 出典の一覧は事実確認のあとに機械で付ける（AIに書かせるとURLを写し間違えることがある）
    body = body.rstrip() + official_mod.sources_section(official or {})
    return Result(title=title or f"{keyword}で選ぶなら", description=desc, body=body,
                  top=top, ok=not [p for p in problems if not p.startswith(STYLE)],
                  issues=problems, reports=reports)


def market_summary(market: dict) -> dict:
    """選択ページから届いた集計値を、数値として使える形にそろえる。"""
    out = {}
    for key in ("total", "sampled", "priceMedian", "priceMin", "priceMax"):
        try:
            out[key] = int(market.get(key))
        except (TypeError, ValueError):
            pass
    for key in ("ratingAverage", "freeShippingRate"):
        try:
            out[key] = float(market.get(key))
        except (TypeError, ValueError):
            pass
    return out


RELEVANCE_PROMPT = """\
あなたは商品紹介サイトの「確認担当」です。
記事のキーワードと、紹介しようとしている商品の名前を渡します。
キーワードで検索した人が探している種類の商品ではないもの（例：キーワードが
「ワイヤレスイヤホン」なのに、CDプレーヤーやスピーカー、ケース、交換用パーツなど）を見つけてください。

■ 記事のキーワード
{keyword}

■ 商品
{names}

━━━━━━━━━━━━━━━━━━━━
・商品名に宣伝の言葉が多く入っていても、本体が何の商品かで判断する。
・同じ種類の商品の中での違い（価格帯・形・機能）は問題にしない。
・迷う場合は「関係あり」とする。

■ 出力（JSONのみ）
{{"unrelated": [{{"n": 商品番号, "reason": "何の商品で、なぜ外すか"}}]}}
すべて関係あれば {{"unrelated": []}} だけを返します。
"""


def check_relevance(keyword: str, products: list[dict], complete: Complete,
                    log=print) -> tuple[list[dict], list[str], list[str]]:
    """キーワードと関係のない商品を外す。

    返り値は (残す商品, 外した商品の説明, 保留にすべき問題)。
    外すと2個未満になる場合は外さず、運営者に確認してもらう。
    確認自体に失敗したときは、何も外さずに先へ進む（記事作りを止めない）。
    """
    names = "\n".join(f"[商品{i}] {p.get('itemName', '')[:150]}" for i, p in enumerate(products, 1))
    try:
        text = complete(RELEVANCE_PROMPT.format(keyword=keyword, names=names),
                        "", 8000, None, light=True)
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start:end + 1]) if start != -1 and end != -1 else {}
    except Exception as exc:                        # noqa: BLE001
        log(f"        関連性の確認をできませんでした: {str(exc)[:120]}")
        return products, [], []
    drop: dict[int, str] = {}
    for item in data.get("unrelated") or [] if isinstance(data, dict) else []:
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= n <= len(products):
            drop[n] = str(item.get("reason") or "")[:120]
    if not drop:
        return products, [], []
    notes = [f"商品{n}（{products[n - 1].get('itemName', '')[:30]}…）：{r}" for n, r in sorted(drop.items())]
    kept = [p for i, p in enumerate(products, 1) if i not in drop]
    if len(kept) < 2:
        log("        キーワードと関係のない商品がありますが、外すと2個未満になるので保留にします")
        return products, [], ["キーワードと関係のない商品が含まれている可能性があります：" + "／".join(notes)]
    for note in notes:
        log(f"        外しました：{note}")
    return kept, notes, []


def fallback_market(products: list[dict]) -> dict:
    """集計が届かなかったとき、選んだ商品だけで最低限の値を作る。"""
    prices = [int(p["itemPrice"]) for p in products if p.get("itemPrice")]
    if not prices:
        return {}
    return {"sampled": len(products), "priceMedian": int(median(prices)),
            "priceMin": min(prices), "priceMax": max(prices)}
