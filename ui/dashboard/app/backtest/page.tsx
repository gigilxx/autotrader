"use client";

export default function BacktestPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">백테스트 결과</h1>
      <p className="text-gray-400 text-sm">
        백테스트는 CLI로 실행합니다:
      </p>
      <pre className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-xs text-green-400 overflow-x-auto">
{`# k값 최적화 (in-sample/out-of-sample)
python -m backtest.optimize --symbol 005930 --start 20230101 --end 20241231 --csv result.csv

# KOSPI200 종목 선별
python -m backtest.screener --start 20230101 --end 20241231 --top 5`}
      </pre>

      <div className="rounded-lg bg-gray-900 border border-gray-800 p-5">
        <h2 className="text-lg font-semibold mb-3">사용 방법</h2>
        <ol className="list-decimal list-inside space-y-2 text-sm text-gray-300">
          <li>
            <code className="bg-gray-800 px-1 rounded text-green-400">pip install pykrx pandas</code>
            {" "}설치
          </li>
          <li>
            위 CLI 명령으로 백테스트 실행 → CSV 저장
          </li>
          <li>
            결과 CSV를 이 페이지에 업로드하면 차트로 시각화 (추후 구현)
          </li>
        </ol>
      </div>

      <div className="rounded-lg bg-yellow-900/20 border border-yellow-700/40 p-4 text-sm text-yellow-300">
        <p className="font-semibold mb-1">주의</p>
        <ul className="list-disc list-inside space-y-1 text-yellow-300/80">
          <li>백테스트는 과거 성과이며 미래 수익을 보장하지 않습니다.</li>
          <li>목표가에서 즉시 체결 가정 — 실제 슬리피지는 다를 수 있습니다.</li>
          <li>in-sample 최적 k값이 out-of-sample에서 악화되면 과최적화 주의.</li>
        </ul>
      </div>
    </div>
  );
}
