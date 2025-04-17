from pymongo import MongoClient
import certifi

# 🔹 MongoDB Connection URI
MONGO_URI = "mongodb+srv://dobriyalhitesh1:L6D9qLy5H4l196cw@cluster0.6sx9pme.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# 🔹 Connect to MongoDB
mongo_client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where())

# 🔹 Database References
db = mongo_client['Ils']
session_collection = db['SessionData']  # Collection for session management
user_collection = db['UserAuthData']  # Collection for user authentication
print(user_collection.find_one("divisha.agarwal@straive.co"))
print("✅ MongoDB Connection Established!")
