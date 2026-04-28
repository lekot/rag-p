import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function PricingPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <header>
        <h1 className="text-3xl font-bold mb-2">Тарифы</h1>
        <p className="text-sm text-muted-foreground">
          Pay-as-you-go: платите только за то, что фактически использовали. Без подписок, без минимальной комиссии.
          Все цены в USD; оплата в RUB по курсу ЦБ РФ + 3% курсового резерва.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Стоимость токенов LLM</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left py-2">Модель</th>
                <th className="text-right py-2">Prompt / 1K токенов</th>
                <th className="text-right py-2">Completion / 1K токенов</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b">
                <td className="py-2">DeepSeek v4 Flash (default)</td>
                <td className="text-right py-2 font-mono">$0.00027</td>
                <td className="text-right py-2 font-mono">$0.0011</td>
              </tr>
              <tr>
                <td className="py-2">OpenAI GPT-4o mini (опционально)</td>
                <td className="text-right py-2 font-mono">$0.00015</td>
                <td className="text-right py-2 font-mono">$0.0006</td>
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Стоимость одного RAG-запроса (Q)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="font-mono bg-muted p-3 rounded text-xs">
            Q_cost = (prompt_tokens × prompt_rate + completion_tokens × completion_rate) / 1000
          </p>
          <p>
            <strong>Pretty формула:</strong> чем длиннее контекст и ответ — тем дороже запрос. Retrieval и rerank выполняются на нашей стороне и в стоимость токенов не входят (входят в workspace base, см. ниже).
          </p>
          <div>
            <p className="text-muted-foreground mb-1">Пример (DeepSeek v4 Flash):</p>
            <ul className="list-disc list-inside space-y-1">
              <li>300 prompt + 100 completion = 300×0.00027/1000 + 100×0.0011/1000 ≈ <strong>$0.00019</strong></li>
              <li>1500 prompt + 400 completion ≈ <strong>$0.00085</strong></li>
              <li>4000 prompt + 800 completion ≈ <strong>$0.0019</strong></li>
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
            Exp_cost ≈ Exp_units × средняя_стоимость_Q
          </p>
          <p>
            Эксперимент = batch-прогон одного и того же набора вопросов через несколько конфигураций pipeline и scoring-метрик. Стоимость считается как сумма всех «scoring units» — каждая такая единица = один RAG-запрос.
          </p>
          <div>
            <p className="text-muted-foreground mb-1">Пример (средний Q ≈ $0.001):</p>
            <ul className="list-disc list-inside space-y-1">
              <li>20 вопросов × 3 варианта × 1 метрика = 60 units ≈ <strong>$0.06</strong></li>
              <li>100 × 12 × 4 = 4 800 units ≈ <strong>$5</strong></li>
              <li>500 × 40 × 4 = 80 000 units ≈ <strong>$80</strong></li>
            </ul>
            <p className="text-xs text-muted-foreground mt-2">
              Перед запуском эксперимента UI покажет preflight estimate — сколько units и примерную стоимость.
            </p>
          </div>
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
            <p className="text-muted-foreground">При балансе ≤ $0 запросы возвращают 402.</p>
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
            <CardTitle>Что не тарифицируется отдельно</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>На пилотной стадии не взимается:</p>
            <ul className="list-disc list-inside text-muted-foreground space-y-1">
              <li>Workspace base (доступ к UI/API)</li>
              <li>Хранение проиндексированных документов</li>
              <li>Embedding-вычисления (запускаются локально на Ollama)</li>
              <li>Retrieval и rerank</li>
            </ul>
            <p className="text-xs text-muted-foreground mt-2">
              Эти статьи будут вынесены в платный workspace-тариф после выхода из пилота.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
