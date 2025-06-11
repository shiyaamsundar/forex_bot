import os
import pandas as pd
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import asyncio
import sys
from datetime import datetime

# Create downloads folder if it doesn't exist
os.makedirs("downloads", exist_ok=True)

def get_timestamp():
    """Get current timestamp for unique filenames"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

# Filtering logic
def filter_stocks(df):
    try:
        df["Company PE"] = pd.to_numeric(df["Company PE"], errors="coerce")
        df["Industry PE"] = pd.to_numeric(df["Industry PE"], errors="coerce")
        df["ROE"] = pd.to_numeric(df["ROE"], errors="coerce")
        df["EPS"] = pd.to_numeric(df["EPS"], errors="coerce")
        df["PB Ratio"] = pd.to_numeric(df["PB Ratio"], errors="coerce")

        return df[
            (df["Company PE"] > df["Industry PE"]) &
            (df["ROE"].between(10, 15)) &
            (df["EPS"].between(10, 15)) &
            (df["PB Ratio"].between(1, 5))
        ]
    except Exception as e:
        print(f"Error in filtering: {e}")
        return pd.DataFrame()

# Handler for uploaded Excel file
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    if doc.mime_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        try:
            # Download the file with timestamp to avoid conflicts
            timestamp = get_timestamp()
            input_file = f"downloads/input_{timestamp}.xlsx"
            output_file = f"downloads/filtered_stocks_{timestamp}.xlsx"
            
            # Download the file
            file = await context.bot.get_file(doc.file_id)
            await file.download_to_drive(input_file)
            
            # Process the file
            df = pd.read_excel(input_file)
            filtered = filter_stocks(df)

            if filtered.empty:
                await update.message.reply_text("No stocks matched the criteria.")
            else:
                # Save filtered results
                filtered.to_excel(output_file, index=False)
                
                # Send the filtered file
                await update.message.reply_text("Processing complete! Here are the filtered stocks:")
                await update.message.reply_document(InputFile(output_file))
                
                # Clean up files
                try:
                    os.remove(input_file)
                    os.remove(output_file)
                except Exception as e:
                    print(f"Error cleaning up files: {e}")

        except Exception as e:
            await update.message.reply_text(f"Error processing the file: {e}")
    else:
        await update.message.reply_text("Please send a valid Excel (.xlsx) file.")

def run_bot():
    """Run the bot."""
    # Create the Application
    application = ApplicationBuilder().token("8040313941:AAFWcrp034rPZ4D87icX05z-_JeQZ2mMBa0").build()

    # Add handler
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Bot is running...")
    print("Send any Excel file to process it...")
    
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        # Windows compatibility fix
        if sys.platform.startswith('win'):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # Run the bot
        run_bot()
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Error: {e}")
