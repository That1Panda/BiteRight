import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import re

# SQLAlchemy Setup
Base = declarative_base()
engine = create_engine('sqlite:///nutrition_tracker.db')  # SQLite database
Session = sessionmaker(bind=engine)
db_session = Session()

# Database Models
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    foods = relationship("UserFood", back_populates="user")

class UserFood(Base):
    __tablename__ = 'user_foods'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    food_name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    user = relationship("User", back_populates="foods")

# Create tables
Base.metadata.create_all(engine)

# Initial Users
def initialize_users():
    if not db_session.query(User).first():
        users = [
            User(username="admin", password="admin123", role="admin"),
            User(username="user1", password="password1", role="user"),
            User(username="user2", password="password2", role="user"),
        ]
        db_session.add_all(users)
        db_session.commit()

initialize_users()

# URL and scraping
url = "https://fitaudit.com/food"
try:
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', class_="pr__ind_c_left vertical_pseudo")
    result = {link['title']: link['href'] for link in links}
except requests.exceptions.RequestException as e:
    st.error(f"Error fetching the URL: {e}")
    st.stop()

# Predefined foods
foods = result.keys()
cols = ['vitamins', 'minerals', 'amino', 'calories']
data = {}
elements = {}

# Login function
def login():
    st.session_state['logged_in'] = False
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = db_session.query(User).filter_by(username=username, password=password).first()
        if user:
            st.session_state['logged_in'] = True
            st.session_state['role'] = user.role
            st.session_state['username'] = user.username
            st.session_state['user_id'] = user.id
        else:
            st.error("Invalid credentials")

# Food Dataframe Generation
def generate_food_dataframe(user_id):
    user_foods = db_session.query(UserFood).filter_by(user_id=user_id).all()
    selected_foods = {food.food_name: food.amount for food in user_foods}

    if not selected_foods:
        return pd.DataFrame(), pd.DataFrame()  # Return empty DataFrames if no foods

    nutrients_data = {}
    macro_data = {}

    for food, amount in tqdm(selected_foods.items()):
        try:
            for col in cols:
                new_url = result[food] + "/" + col
                response = requests.get(new_url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                if col == "calories":
                    # Handle caloric and macronutrient data
                    meta_description = soup.find("meta", {"name": "description"})
                    if meta_description:
                        content = meta_description.get("content", "").strip()

                        # Use regex to extract nutritional values
                        calories = re.search(r"(\d+)\s+calories", content)
                        carbs = re.search(r"([\d.]+)\s+grams\s+of\s+carbohydrate", content)
                        protein = re.search(r"([\d.]+)\s+grams\s+of\s+protein", content)
                        fats = re.search(r"([\d.]+)\s+grams\s+of\s+fat", content)

                        macro_data[food] = {
                            "Calories": (int(calories.group(1)) if calories else 0) * (amount / 100),
                            "Carbohydrates": (float(carbs.group(1)) if carbs else 0) * (amount / 100),
                            "Protein": (float(protein.group(1)) if protein else 0) * (amount / 100),
                            "Fats": (float(fats.group(1)) if fats else 0) * (amount / 100),
                            "Amount (gm)": amount,
                        }

                else:
                    # Handle vitamins, minerals, and amino acids
                    rows = soup.select(f'table#{col}_tbl tbody tr')[1:]
                    for row in rows:
                        name = row.select_one('.tbl-name a').get_text(strip=True)
                        value = row.select_one('.tbl-value').get_text(strip=True).replace("g", "").strip()
                        tip = row.select_one('.tbl-chart').get('tip') if row.select_one('.tbl-chart') else None

                        if food not in nutrients_data:
                            nutrients_data[food] = {}

                        nutrients_data[food][name] = {
                            'value': value,
                            'tip': tip[:-1] if tip else 0,
                            'amount': amount,
                            'col': col,
                        }
        except Exception as e:
            st.warning(f"Error processing {food} for {col}: {e}")

    # Create nutrient dataframe
    nutrient_columns = list({name for food_data in nutrients_data.values() for name in food_data})
    nutrient_df = pd.DataFrame(index=selected_foods.keys(), columns=nutrient_columns)

    for food, elements in nutrients_data.items():
        for element, values in elements.items():
            try:
                nutrient_df.loc[food, element] = float(values['tip']) * (values['amount'] / 100)
            except ValueError:
                nutrient_df.loc[food, element] = 0

    # Order columns for better readability
    sorted_cols = elements['vitamins'] + elements['minerals'] + elements['amino'] if 'vitamins' in elements else nutrient_columns
    nutrient_df = nutrient_df[sorted_cols]

    # Create macronutrient dataframe
    macro_df = pd.DataFrame(macro_data).T
    macro_df.loc['Total'] = macro_df.sum(axis=0)

    return nutrient_df, macro_df



# Main Streamlit App
def main():
    if "logged_in" not in st.session_state or not st.session_state['logged_in']:
        signup_or_login = st.sidebar.radio("Choose Action", ["Login", "Sign Up"])
        
        if signup_or_login == "Login":
            login()
        elif signup_or_login == "Sign Up":
            st.title("Sign Up")
            new_username = st.text_input("Username")
            new_password = st.text_input("Password", type="password")
            new_role = st.selectbox("Role", ["user", "admin"])
            if st.button("Create Account"):
                if db_session.query(User).filter_by(username=new_username).first():
                    st.error("Username already exists. Please choose a different one.")
                else:
                    new_user = User(username=new_username, password=new_password, role=new_role)
                    db_session.add(new_user)
                    db_session.commit()
                    st.success("Account created successfully! Please log in.")
    else:
        st.sidebar.title(f"Welcome, {st.session_state['username']}")
        if st.sidebar.button("Logout"):
            st.session_state['logged_in'] = False
            st.experimental_rerun()

        user_id = st.session_state['user_id']
        role = st.session_state.get('role')

        if role == "admin":
            st.title("Admin Dashboard")
            st.subheader("All User Data")
            all_users = db_session.query(User).all()
            for user in all_users:
                st.write(f"User: {user.username}, Role: {user.role}")
        else:
            st.title("BiteRight - Nutrition Tracker")
            st.subheader("Add or Remove Food")
            user_food = st.selectbox("Select Food", list(foods))
            user_amount = st.number_input("Enter Amount (in grams)", min_value=0, value=100)

            if st.button("Add Food"):
                food_entry = db_session.query(UserFood).filter_by(user_id=user_id, food_name=user_food).first()
                if food_entry:
                    food_entry.amount += user_amount
                else:
                    new_food = UserFood(user_id=user_id, food_name=user_food, amount=user_amount)
                    db_session.add(new_food)
                db_session.commit()
                st.success("Food added successfully!")

            if st.button("Remove Food"):
                food_entry = db_session.query(UserFood).filter_by(user_id=user_id, food_name=user_food).first()
                if food_entry:
                    db_session.delete(food_entry)
                    db_session.commit()
                    st.success("Food removed successfully!")
                else:
                    st.warning("Food not found.")

            # Display user food DataFrame
            st.subheader("Your Nutrition Data")
            df,df2 = generate_food_dataframe(user_id)
            st.dataframe(df)

            if not df.empty:
                # Display the summarized table from get_nutrient_values

                st.subheader("Caloric and Macronutrient Breakdown")
                st.dataframe(df2)
                
                # Summed nutrients with filter
                st.subheader("Summed Nutrient Values (Sorted)")
                summed_df = df.sum(axis=0).sort_values(ascending=True).to_frame(name="Total").reset_index()
                summed_df.columns = ["Nutrient", "Total"]
            
                # Dropdown menu for nutrients
                available_nutrients = summed_df['Nutrient'].tolist()
                selected_nutrients = st.multiselect("Select Nutrients to not Display", available_nutrients)
                filtered_summed_df = summed_df[~summed_df['Nutrient'].isin(selected_nutrients)]
                # filtered_summed_df = summed_df[summed_df['Nutrient'].isin(selected_nutrients)]
                st.dataframe(filtered_summed_df)

                # Display total EAA values
                st.subheader("Total Essential Amino Acids (EAA)")
                eaas = [
                    'Tryptophan', 'Threonine', 'Isoleucine', 'Leucine',
                    'Lysine', 'Methionine', 'Phenylalanine', 'Valine', 'Histidine'
                ]
                eaa_df = summed_df[summed_df['Nutrient'].isin(eaas)]
                total_eaas = eaa_df['Total'].sum()
                st.dataframe(eaa_df)

                st.write(f"**Total EAA Sum**: {total_eaas}")




# Run the app
if __name__ == "__main__":
    main()
