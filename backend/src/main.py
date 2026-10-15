from fastapi import FastAPI
from .api import vendor_files, vendors

app = FastAPI(title="Document intelligence")

app.include_router(vendors.router)
app.include_router(vendor_files.router)

