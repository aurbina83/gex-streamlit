import json
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pandas as pd
import requests
from matplotlib import dates
import streamlit as st

# Set plot style
plt.style.use("seaborn-v0_8-dark")
for param in ["figure.facecolor", "axes.facecolor", "savefig.facecolor"]:
    plt.rcParams[param] = "#212946"
for param in ["text.color", "axes.labelcolor", "xtick.color", "ytick.color"]:
    plt.rcParams[param] = "0.9"

contract_size = 100

# Set page configuration and style
st.set_page_config(
    page_title="Market Data Analysis App",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)
st.markdown(
    """
<style>
.main {
   background-color: #212946;
}
</style>
""",
    unsafe_allow_html=True,
)


def scrape_data(ticker):
    """Scrape data from CBOE website"""
    data = None
    # check if data folder exists
    if "data" not in os.listdir():
        os.mkdir("data")
    # Check if data is already downloaded
    if f"{ticker}.json" in os.listdir("data"):
        f = open(f"data/{ticker}.json")
        data = pd.DataFrame.from_dict(json.load(f))
        timestamp = datetime.fromtimestamp(data["timestamp"])
        # if timestamp is older than 1 day, request new data
        data = None if (datetime.now() - timestamp).days > 1 else data
    if not data:
        # Request data and save it to file
        try:
            data = requests.get(
                f"https://cdn.cboe.com/api/global/delayed_quotes/options/_{ticker}.json"
            )
            with open(f"data/{ticker}.json", "w") as f:
                json.dump(data.json(), f)

        except ValueError:
            data = requests.get(
                f"https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
            )
            with open(f"data/{ticker}.json", "w") as f:
                json.dump(data.json(), f)
        # Convert json to pandas DataFrame
        data = pd.DataFrame.from_dict(data.json())

    spot_price = data.loc["current_price", "data"]
    option_data = pd.DataFrame(data.loc["options", "data"])

    return spot_price, fix_option_data(option_data)


def fix_option_data(data):
    """
    Fix option data columns.

    From the name of the option derive type of option, expiration and strike price
    """
    data["type"] = data.option.str.extract(r"\d([A-Z])\d")
    data["strike"] = data.option.str.extract(r"\d[A-Z](\d+)\d\d\d").astype(int)
    data["expiration"] = data.option.str.extract(r"[A-Z](\d+)").astype(str)
    # Convert expiration to datetime format
    data["expiration"] = pd.to_datetime(data["expiration"], format="%y%m%d")
    return data


def compute_total_gex(spot, data):
    """Compute dealers' total GEX"""
    # Compute gamma exposure for each option
    data["GEX"] = spot * data.gamma * data.open_interest * contract_size * spot * 0.01

    # For put option we assume negative gamma, i.e. dealers sell puts and buy calls
    data["GEX"] = data.apply(lambda x: -x.GEX if x.type == "P" else x.GEX, axis=1)
    print(f"Total notional GEX: ${round(data.GEX.sum() / 10 ** 9, 4)} Bn")


def compute_gex_by_strike(spot, data, ticker):
    """Compute and plot GEX by strike"""
    # Compute total GEX by strike
    gex_by_strike = data.groupby("strike")["GEX"].sum() / 10**9

    # Limit data to +- 15% from spot price
    limit_criteria = (gex_by_strike.index > spot * 0.85) & (
        gex_by_strike.index < spot * 1.15
    )

    # Create a plot
    fig, ax = plt.subplots()
    ax.bar(
        gex_by_strike[limit_criteria].index,
        gex_by_strike[limit_criteria],
        color="#FE53BB",
        alpha=0.5,
    )
    ax.grid(color="#2A3459")
    ax.set_xlabel("Strike", fontweight="heavy")
    ax.set_ylabel("Gamma Exposure (Bn$)", fontweight="heavy")
    ax.set_title(f"{ticker} GEX by Strike", fontweight="heavy")
    st.pyplot(fig)  # Streamlit function to display the figure


def compute_gex_by_expiration(data, ticker):
    """Compute and plot GEX by expiration"""
    # Limit data to one year
    selected_date = datetime.today() + timedelta(days=365)
    data = data[data["expiration"] < selected_date]

    # Compute GEX by expiration date
    gex_by_expiration = data.groupby("expiration")["GEX"].sum() / 10**9

    # Create a plot
    fig, ax = plt.subplots()
    ax.bar(
        gex_by_expiration.index,
        gex_by_expiration.values,
        color="#FE53BB",
        alpha=0.5,
    )
    ax.grid(color="#2A3459")
    ax.set_xlabel("Expiration Date", fontweight="heavy")
    ax.set_ylabel("Gamma Exposure (Bn$)", fontweight="heavy")
    ax.set_title(f"{ticker} GEX by Expiration", fontweight="heavy")
    plt.xticks(rotation=45)
    st.pyplot(fig)  # Streamlit function to display the figure


def print_gex_surface(spot, data, ticker):
    """Plot 3D surface of GEX"""
    # Limit data to 1 year and +- 15% from ATM
    selected_date = datetime.today() + timedelta(days=365)
    limit_criteria = (
        (data["expiration"] < selected_date)
        & (data["strike"] > spot * 0.85)
        & (data["strike"] < spot * 1.15)
    )
    limited_data = data[limit_criteria]

    # Compute GEX by expiration and strike
    grouped_data = limited_data.groupby(["expiration", "strike"])["GEX"].sum() / 10**6
    grouped_data = grouped_data.reset_index()

    # Create a 3D plot
    fig = plt.figure()
    ax = fig.add_subplot(111, projection="3d")
    ax.plot_trisurf(
        grouped_data["strike"],
        dates.date2num(grouped_data["expiration"]),
        grouped_data["GEX"],
        cmap="seismic_r",
    )
    ax.set_xlabel("Strike Price", fontweight="light")
    ax.set_ylabel("Expiration Date", fontweight="light")
    ax.set_zlabel("Gamma (M$)", fontweight="light")
    ax.yaxis.set_major_formatter(dates.DateFormatter("%m/%d/%y"))
    st.pyplot(fig)  # Streamlit function to display the figure


def main():
    st.title("Gamma Exposure by Strike and Expiration")
    ticker = st.text_input("Enter the Ticker Symbol", "AAPL").upper()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Run Analysis"):
            spot_price, option_data = scrape_data(ticker)
            if option_data is not None and spot_price is not None:
                compute_total_gex(spot_price, option_data)
                compute_gex_by_strike(spot_price, option_data, ticker)
                compute_gex_by_expiration(option_data, ticker)
                print_gex_surface(spot_price, option_data, ticker)
            else:
                st.error("Data retrieval was unsuccessful.")


if __name__ == "__main__":
    main()
