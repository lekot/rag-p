import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Plan {
  name: string;
  price: string;
  tagline: string;
  highlight?: boolean;
  features: string[];
}

const PLANS: Plan[] = [
  {
    name: "Personal",
    price: "100 ₽/мес",
    tagline: "Аккаунт «попробовать»",
    features: [
      "≈ 1 000 RAG-запросов",
      "100 МБ хранения",
      "1 пользователь",
      "60 запросов/мин",
      "Email-поддержка",
    ],
  },
  {
    name: "Pro",
    price: "1 500 ₽/мес",
    tagline: "Команда до 5 человек",
    highlight: true,
    features: [
      "≈ 20 000 RAG-запросов",
      "2 ГБ хранения",
      "До 5 пользователей",
      "300 запросов/мин",
      "Дашборд usage и cost-breakdown",
      "Email-поддержка в приоритете",
    ],
  },
  {
    name: "Corporate",
    price: "5 000 ₽/мес",
    tagline: "Компания до 25 человек",
    features: [
      "≈ 70 000 RAG-запросов",
      "8 ГБ хранения",
      "До 25 пользователей",
      "1 000 запросов/мин",
      "Audit log и роли",
      "Pay-as-you-go при перерасходе",
    ],
  },
  {
    name: "Enterprise",
    price: "60 000 ₽/мес",
    tagline: "Большие команды и SLA",
    features: [
      "≈ 1 000 000 RAG-запросов",
      "100 ГБ хранения",
      "Без лимита по пользователям",
      "Без лимита rpm",
      "SLA 99,9%",
      "Выделенная поддержка",
      "On-premise по запросу",
    ],
  },
];

export default function PricingPage() {
  return (
    <div className="max-w-6xl mx-auto space-y-10">
      <header className="text-center space-y-2">
        <h1 className="text-3xl font-bold">Тарифы</h1>
        <p className="text-sm text-muted-foreground">
          Выберите план под объём задач. Минимальный — Personal за 100 ₽: достаточно, чтобы попробовать платформу
          на ~1 000 запросов. Бесплатного триала нет — это позволяет держать честные тарифы и не дотировать сервис из маржи платных клиентов.
        </p>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {PLANS.map((plan) => (
          <Card
            key={plan.name}
            className={
              plan.highlight
                ? "border-primary shadow-lg ring-2 ring-primary/20"
                : ""
            }
          >
            <CardHeader>
              <CardTitle className="text-lg">{plan.name}</CardTitle>
              <div className="text-2xl font-bold">{plan.price}</div>
              <p className="text-xs text-muted-foreground">{plan.tagline}</p>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1.5 text-xs list-disc list-inside">
                {plan.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        ))}
      </div>

      <details className="border rounded-lg p-4 text-sm">
        <summary className="cursor-pointer font-semibold">
          Как мы считаем стоимость запроса
        </summary>
        <div className="mt-4 space-y-4 text-sm">
          <p>
            «1 запрос» в тарифах — это типичный RAG-запрос (≈ 1500 input + 400 output токенов через DeepSeek v4 Flash).
            Реальная стоимость считается по факту, а не по штучно: в тариф просто включён бюджет,
            эквивалентный заявленному количеству запросов.
          </p>

          <div>
            <p className="font-medium mb-1">Стоимость токенов (если считать вручную):</p>
            <ul className="list-disc list-inside text-xs space-y-1">
              <li>Input: 0,022 ₽ за 1 000 токенов (22 ₽/млн)</li>
              <li>Output: 0,055 ₽ за 1 000 токенов (55 ₽/млн)</li>
              <li>Смешанный (2:1) ≈ 33 ₽/млн, порог окупаемости ≈ 21 ₽/млн</li>
            </ul>
            <p className="text-xs text-muted-foreground mt-2">
              В цену уже входят: оптовая стоимость DeepSeek, 6% VAT, 6% НПД самозанятого, 3,5% ЮKassa и операционная маржа.
            </p>
          </div>

          <div>
            <p className="font-medium mb-1">Стоимость эксперимента (Exp):</p>
            <p className="font-mono bg-muted p-2 rounded text-xs">
              Exp_units = вопросы × варианты_pipeline × метрики
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Каждая «единица оценки» = один RAG-запрос. Например, 100 × 12 × 4 ≈ 4 800 units ≈ 265 ₽.
              На тарифах units списываются из включённого бакета запросов.
            </p>
          </div>

          <div>
            <p className="font-medium mb-1">Compute и Storage в проде:</p>
            <ul className="list-disc list-inside text-xs space-y-1">
              <li>Compute time: 150 ₽/час (0,042 ₽/сек) — за время выполнения Q и Exp</li>
              <li>Storage: 60 ₽ за 1 ГБ в месяц, первые 100 МБ всегда бесплатно</li>
            </ul>
            <p className="text-xs text-muted-foreground mt-1">
              На пилотной стадии compute не списывается с баланса. Storage сверх включённого в тариф — pay-as-you-go.
            </p>
          </div>

          <div>
            <p className="font-medium mb-1">Лимиты и блокировки:</p>
            <ul className="list-disc list-inside text-xs space-y-1">
              <li>При балансе ≤ 0 запросы возвращают 402 Payment Required</li>
              <li>При превышении rpm — 429 Too Many Requests с заголовком Retry-After</li>
              <li>На Personal/Pro перерасход бакета блокирует запросы; на Corporate/Enterprise — pay-as-you-go</li>
            </ul>
          </div>

          <div>
            <p className="font-medium mb-1">Оплата:</p>
            <ul className="list-disc list-inside text-xs space-y-1">
              <li>Банковские карты через ЮKassa</li>
              <li>Минимальный платёж — 100 ₽</li>
              <li>Чек ФНС автоматически через приложение «Мой налог»</li>
              <li>Возврат — в течение 14 дней при списаниях ≤ 10% от суммы пополнения</li>
            </ul>
          </div>
        </div>
      </details>
    </div>
  );
}
