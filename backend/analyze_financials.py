import sys
import json
import os
import pandas as pd
import requests  # <-- Import requests for API calls
from financial_utils import (
    read_financials,
    compute_ratios,
    score_ratios,
    analyze_trends,
)
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# -------------------------------
# NEW: Finnhub API Function
# -------------------------------
def fetch_benchmark_data_finnhub(ticker: str) -> dict:
    """
    Fetches industry average metrics from Finnhub based on a peer ticker.
    """
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        print("Warning: FINNHUB_API_KEY not found. Skipping benchmarks.")
        return {}

    # This map translates Finnhub's metric names to our internal names
    # This is CRUCIAL for the frontend chart to match
    FINNHUB_TO_INTERNAL_MAP = {
        "netProfitMarginTTM": "Net Profit Margin",
        "roaTTM": "Return on Assets (ROA)",
        "debtToEquityTTM": "Debt to Equity Ratio",  # <-- FIX: Was "debt/equityTTM"
        "currentRatioTTM": "Current Ratio",
        "grossMarginTTM": "Gross Margin",
        "quickRatioTTM": "Quick Ratio",
    }

    try:
        # Use Finnhub's 'stock/metric' endpoint to get basic financials and industry averages
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={api_key}"
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx, 5xx)
        data = response.json()

        if "metric" not in data or not data["metric"]:
            print(
                f"Warning: No metric data found for ticker {ticker}. Is the ticker valid?"
            )
            return {}

        industry_metrics = data.get("metric", {})
        average_ratios = {}

        # Loop through our map and extract the industry average for each metric
        for finnhub_key, internal_key in FINNHUB_TO_INTERNAL_MAP.items():

            # --- BUG FIX ---
            # Removed the outer check 'if finnhub_key in industry_metrics:'
            # We should ALWAYS look for the industry key, even if the company key is missing.

            industry_avg_key = None

            # --- FIX: Handle different industry key naming conventions ---

            # Case 1: Special case for debtToEquity
            if finnhub_key == "debtToEquityTTM":
                industry_avg_key = "industryDebtToEquity"  # No TTM, 'To' is capitalized

            # Case 2: General case (remove TTM, capitalize first letter)
            else:
                key_without_ttm = finnhub_key.replace("TTM", "")
                industry_avg_key = (
                    f"industry{key_without_ttm[0].upper() + key_without_ttm[1:]}"
                )

            # End of FIX ---

            if industry_avg_key and industry_avg_key in industry_metrics:
                average_ratios[internal_key] = industry_metrics[industry_avg_key]
            else:
                # Fallback if the specific industry key isn't present
                print(
                    f"Warning: Could not find industry key '{industry_avg_key}' for {finnhub_key}."
                )
                average_ratios[internal_key] = None

        # We only return the 'average' dict, as 'best-in-class' isn't provided by this endpoint
        return {"average": average_ratios}

    except requests.exceptions.RequestException as e:
        print(f"Error fetching Finnhub data: {e}")
        return {}
    except Exception as e:
        print(f"Error processing benchmark data: {e}")
        return {}


# -------------------------------
# AI Suggestions Function (MODIFIED)
# -------------------------------
def generate_ai_insights(ratios, sub_scores, overall_score, benchmark_data):
    """
    Uses the OpenAI API to generate improvement recommendations,
    now with comparative benchmark data.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Error: OPENAI_API_KEY not found. Please set it in your .env file."

    client = OpenAI(api_key=api_key)
    context = {
        "your_company_ratios": ratios,
        "sub_scores": sub_scores,
        "overall_score": overall_score,
        "peer_benchmarks": benchmark_data,  # This will contain {'average': {...}}
    }

    # MODIFIED PROMPT FOR STRATEGIC COMPARISON
    prompt = f"""
    Analyze the following financial data for a company:
    {json.dumps(context, indent=2)}

    Instructions:
    1. Act as a senior financial strategist.
    2. Compare the company's ratios ("your_company_ratios") to the "Industry Average" found in "peer_benchmarks['average']".
    3. Identify the **single biggest strength** where the company outperforms the average.
    4. Identify the **single biggest weakness** where the company lags the average.
    5. Based on this comparison, deduce the company's likely **strategy** (e.g., "premium pricing," "cost leadership," "high leverage").
    6. Provide **2-3 actionable insights** for improvement, focusing on the weakest area.
    7. Use markdown (###, ####, **text**). Keep the entire response to 3-4 short paragraphs.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert financial consultant for SMEs. You provide **concise, scannable, and actionable** advice. Keep your entire response to 3-4 short paragraphs.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error connecting to OpenAI API: {e}"


# -------------------------------
# API-Callable Analysis Function (MODIFIED)
# -------------------------------
def run_analysis(file_path: str, ticker: str) -> dict:
    """
    Runs the full financial analysis and returns a dictionary (JSON).
    This function is called by the Flask server and now accepts a 'ticker'.
    """
    try:
        financials = read_financials(file_path)
        if financials is None:
            return {
                "error": "Failed to read financial data. Is the file corrupted or in the wrong format?"
            }

        # 1. Compute Ratios
        ratios = compute_ratios(financials)

        # 2. Compute Scores
        sub_scores, overall_score = score_ratios(ratios)

        # 3. Analyze Trends
        trend_df = analyze_trends(financials)
        # Convert DataFrame to JSON-friendly format
        trend_df_json = trend_df.reset_index().rename(columns={"index": "Metric"})
        trend_json = trend_df_json.to_dict(orient="records")

        # --- NEW STEP: Fetch Benchmarks from Finnhub ---
        benchmark_data = fetch_benchmark_data_finnhub(ticker)

        # 4. Generate AI Insights (now with benchmark data)
        ai_insights = generate_ai_insights(
            ratios, sub_scores, overall_score, benchmark_data
        )

        # 5. Assemble final JSON response
        return {
            "ratios": ratios,
            "sub_scores": sub_scores,
            "overall_score": overall_score,
            "trends": trend_json,
            "ai_insights": ai_insights,
            "benchmarks": benchmark_data,  # <-- Pass benchmarks to frontend
        }
    except Exception as e:
        return {
            "error": f"An error occurred during analysis: {e}. Check the Excel file for correct sheet names (e.g., 'Income Statement', 'Balance Sheet') and formats."
        }


# -------------------------------
# Original Main Function (for CLI use)
# -------------------------------
def main_cli(file_path, ticker="AAPL"):
    """
    Original command-line interface.
    This now calls run_analysis and prints the results.
    """
    print(f"\n📊 Analyzing financials from: {file_path}")
    print(f"📈 Benchmarking against peer ticker: {ticker}")
    result = run_analysis(file_path, ticker)

    if "error" in result:
        print(f"\n--- ERROR --- \n{result['error']}")
        return

    # ... (rest of the print statements for CLI) ...

    # Print Ratios
    print("\n📈 Key Financial Ratios (Latest Year):")
    for k, v in result.get("ratios", {}).items():
        print(f"   {k:<25}: {v:.2f}")

    # Print Scores
    print("\n💡 Sub-scores:")
    for k, v in result.get("sub_scores", {}).items():
        print(f"   {k:<15}: {v:.2f}")
    print(f"\n⭐ Overall Financial Score: {result.get('overall_score', 0):.2f}/100")

    # Print Trends
    print("\n📉 Trend Analysis (3 Years):")
    if result.get("trends"):
        # Re-create DataFrame from the records
        trend_df = pd.DataFrame(result["trends"]).set_index("Metric")
        print(trend_df.to_string(index=True))

    # Print Benchmarks
    print("\n🌍 Peer Benchmarks (Industry Average):")
    if result.get("benchmarks", {}).get("average"):
        for k, v in result["benchmarks"]["average"].items():
            if v is not None:
                print(f"   {k:<25}: {v:.2f}")
            else:
                print(f"   {k:<25}: N/A")
    else:
        print("   No benchmark data found.")

    # Print AI Insights
    print("\n🤖 AI-Powered Suggestions:")
    print(result.get("ai_insights", "No insights generated."))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_financials.py <path_to_excel_file> [peer_ticker]")
    else:
        peer_ticker = sys.argv[2] if len(sys.argv) > 2 else "AAPL"
        main_cli(sys.argv[1], peer_ticker)
