import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function PricingPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <header>
        <h1 className="text-3xl font-bold mb-2">Тарифы</h1>
        <p className="text-sm text-muted-foreground">
          Pay-as-you-go: платите только за то, что фактически использовали. Без подписок, без минимальной комиссии.
          Цены указаны в рублях, но баланс ведётся в USD — при пополнении через ЮKassa сумма конвертируется
          по курсу ЦБ РФ + 3% курсового резерва.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Стоимость токенов LLM (DeepSeek v4 Flash)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left py-2">Тип</th>
                <th className="text-right py-2">за 1K токенов</th>
                <th className="text-right py-2">за 1M токенов</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b">
                <td className="py-2">Input (вопрос + контекст из RAG)</td>
                <td className="text-right py-2 font-mono">0,02 ₽</td>
                <td className="text-right py-2 font-mono">20 ₽</td>
              </tr>
              <tr>
                <td className="py-2">Output (ответ модели)</td>
                <td className="text-right py-2 font-mono">0,05 ₽</td>
                <td className="text-right py-2 font-mono">50 ₽</td>
              </tr>
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">
            Цены включают комиссии платёжного шлюза, налог самозанятого и операционную маржу.
            Типичный RAG-запрос имеет соотношение input:output примерно 2:1 — это даёт смешанный тариф ~30&nbsp;₽ за 1&nbsp;млн токенов.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Формула стоимости одного RAG-запроса (Q)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="font-mono bg-muted p-3 rounded text-xs">
            Q_cost = input_tokens × 0,02 ₽ / 1K&nbsp;&nbsp;+&nbsp;&nbsp;output_tokens × 0,05 ₽ / 1K
          </p>
          <p>Чем больше контекста модель прочитала и чем длиннее ответ — тем дороже запрос. Сам поиск (retrieval, rerank) на пилотной стадии не тарифицируется.</p>
          <div>
            <p className="text-muted-foreground mb-1">Примеры:</p>
            <ul className="list-disc list-inside space-y-1">
              <li>300 input + 100 output ≈ <strong>0,011 ₽</strong> (~$0.00012)</li>
              <li>1500 input + 400 output ≈ <strong>0,050 ₽</strong> (~$0.00053)</li>
              <li>4000 input + 800 output ≈ <strong>0,12 ₽</strong> (~$0.00126)</li>
            </ul>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Стоимость эксперимента (Exp)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="font-mono bg-muted p-3 rounded text-xs">
            Exp_units = dataset_questions × pipeline_variants × scorer_metrics
            <br />
            Exp_cost ≈ Exp_units × средняя_Q_cost
          </p>
          <p>
            Эксперимент — это batch-прогон вопросов через несколько конфигураций pipeline и метрик. Стоимость складывается из всех Q-запросов, которые он порождает. Перед запуском UI показывает preflight estimate — сколько units и примерную сумму.
          </p>
          <div>
            <p className="text-muted-foreground mb-1">Примеры (средняя Q ≈ 0,05 ₽):</p>
            <ul className="list-disc list-inside space-y-1">
              <li>20 вопросов × 3 варианта × 1 метрика = 60 units ≈ <strong>3 ₽</strong></li>
              <li>100 × 12 × 4 = 4 800 units ≈ <strong>240 ₽</strong></li>
              <li>500 × 40 × 4 = 80 000 units ≈ <strong>4 000 ₽</strong></li>
            </ul>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Compute time (резерв на стадии прода)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="font-mono bg-muted p-3 rounded text-xs">
            compute_cost = duration_seconds × 0,042 ₽ / сек&nbsp;&nbsp;(≈ 150 ₽ / час)
          </p>
          <p>Покрывает CPU/RAM/диск/локальный embedder под Q и Exp. На пилотной стадии compute не списывается с баланса — при выходе в прод включится.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Хранение проиндексированных документов</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="font-mono bg-muted p-3 rounded text-xs">
            storage_cost = max(0, GB − 0,1) × 2 ₽ / GB / месяц
          </p>
          <p>Первые 100 МБ на организацию — бесплатно. Дальше — 2 ₽ за 1 ГБ в месяц (≈ цена Selectel S3 + операционная маржа).</p>
          <p className="text-xs text-muted-foreground">На пилотной стадии тариф не взимается. Тариф введён в прайс, чтобы система не использовалась как облачный бэкап без RAG-нагрузки.</p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Пополнение баланса</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>Минимум — <strong>$1</strong></p>
            <p>Максимум за один платёж — <strong>$1 000</strong></p>
            <p>Стартовый кредит при регистрации — <strong>$1</strong></p>
            <p className="text-muted-foreground">Оплата: банковские карты через ЮKassa.</p>
            <p className="text-muted-foreground">Чек ФНС автоматически через «Мой налог».</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Лимиты</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>60 запросов/мин на API-ключ</p>
            <p>1 000 запросов/мин на организацию</p>
            <p className="text-muted-foreground">При балансе ≤ 0 запросы возвращают 402.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Что входит</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm list-disc list-inside">
              <li>Загрузка датасетов (PDF, DOCX, TXT, MD, JSON, CSV, YAML, XML, HTML)</li>
              <li>Векторный поиск (pgvector)</li>
              <li>RAG-генерация с цитированиями</li>
              <li>Генерация golden Q&amp;A через DeepSeek</li>
              <li>Эксперименты с разными конфигурациями pipeline</li>
              <li>REST API через Bearer-токен</li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Что не тарифицируется на пилоте</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>Бесплатно до выхода в прод:</p>
            <ul className="list-disc list-inside text-muted-foreground space-y-1">
              <li>Workspace base (доступ к UI/API)</li>
              <li>Compute time (CPU/RAM/локальный embedder)</li>
              <li>Storage до 100 МБ — всегда бесплатно</li>
              <li>Retrieval и rerank</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
