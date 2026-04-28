import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function PricingPage() {
  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-2">Тарифы</h1>
      <p className="text-sm text-muted-foreground mb-8">
        Pay-as-you-go. Без подписок, без минимальной комиссии.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Стоимость API-запросов</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="text-left py-2">Модель</th>
                  <th className="text-right py-2">Prompt / 1K</th>
                  <th className="text-right py-2">Completion / 1K</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="py-2">DeepSeek v4 Flash (default)</td>
                  <td className="text-right py-2 font-mono">$0.00027</td>
                  <td className="text-right py-2 font-mono">$0.0011</td>
                </tr>
              </tbody>
            </table>
            <p className="mt-4 text-xs text-muted-foreground">
              Цены указаны в USD. Оплата принимается в RUB по курсу ЦБ РФ + 3% курсового резерва.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Пополнение баланса</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>Минимум пополнения — <strong>$1</strong></p>
            <p>Максимум за один платёж — <strong>$1 000</strong></p>
            <p>Стартовый кредит при регистрации — <strong>$1</strong></p>
            <p className="text-muted-foreground">Способы оплаты: банковские карты (через ЮКassa)</p>
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
              <li>Генерация golden Q&amp;A</li>
              <li>Эксперименты с разными конфигурациями pipeline</li>
              <li>REST API через Bearer-токен</li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Лимиты</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>60 запросов/мин на API-ключ</p>
            <p>1 000 запросов/мин на организацию</p>
            <p className="text-muted-foreground">
              При балансе ≤ $0 запросы возвращают 402.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
