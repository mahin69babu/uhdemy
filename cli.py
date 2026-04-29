import threading
import time
import traceback
import sys
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text
from rich import box
from base import VERSION, LoginException, Scraper, Udemy, scraper_dict, logger


console = Console()


def handle_error(error_message, error=None, exit_program=True):
    logger.error(f"ERROR: {error_message}")
    """
    Handle errors consistently throughout the application.

    Args:
        error_message: User-friendly error message
        error: The exception object (optional)
        exit_program: Whether to exit the program after displaying the error (default: True)
    """
    console.print(
        f"\n[bold white on red] ERROR [/bold white on red] [bold red]{error_message}[/bold red]"
    )

    if error:
        error_details = str(error)
        trace = traceback.format_exc()
        console.print(f"[red]Details: {error_details}[/red]")
        console.print("[yellow]Full traceback:[/yellow]")
        console.print(Panel(trace, border_style="red"))

        logger.exception(f"{error_message} - Details: {error_details}")

    if exit_program:
        sys.exit(1)


# Note: Real-time display functions removed to only show final results


def create_scraping_thread(site: str):
    code_name = scraper_dict[site]
    task_id = udemy.progress.add_task(site, total=100)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            threading.Thread(target=getattr(scraper, code_name), daemon=True).start()
            # Wait up to 1 minute for scraper to start (length != 0)
            start_time = time.time()
            while getattr(scraper, f"{code_name}_length") == 0:
                if time.time() - start_time > 60:
                    raise TimeoutError(f"Timeout waiting for {site} scraper to start.")
                time.sleep(0.1)
            if getattr(scraper, f"{code_name}_length") == -1:
                raise Exception(f"Error in: {site}")

            udemy.progress.update(task_id, total=getattr(scraper, f"{code_name}_length"))

            # Wait up to 1 minute for scraper to finish
            start_time = time.time()
            while not getattr(scraper, f"{code_name}_done") and not getattr(
                scraper, f"{code_name}_error"
            ):
                if time.time() - start_time > 60:
                    raise TimeoutError(f"Timeout waiting for {site} scraper to finish.")
                current = getattr(scraper, f"{code_name}_progress")
                udemy.progress.update(
                    task_id,
                    completed=current,
                    total=getattr(scraper, f"{code_name}_length"),
                )
                time.sleep(0.1)

            udemy.progress.update(
                task_id, completed=getattr(scraper, f"{code_name}_length")
            )
            logger.debug(
                f"Courses Found {code_name}: {len(getattr(scraper, f'{code_name}_data'))}"
            )

            if getattr(scraper, f"{code_name}_error"):
                raise Exception(f"Error in: {site}")
            # Success, break out of retry loop
            return
        except Exception as e:
            error = getattr(scraper, f"{code_name}_error", traceback.format_exc())
            logger.error(f"Error in {site} (attempt {attempt}): {error}")
            console.print(f"[bold red]Error in {site} (attempt {attempt}/3)[/bold red]")
            if attempt == max_retries:
                # Do not exit, just continue after last attempt
                return
            else:
                console.print(f"[yellow]Retrying {site} in 1 second...[/yellow]")
                time.sleep(1)


if __name__ == "__main__":
    try:
        # Initialize Udemy client
        udemy = Udemy("cli")
        udemy.load_settings()
        
        # Login and setup
        login_successful = False
        while not login_successful:
            try:
                # Try browser cookies first
                if udemy.settings["use_browser_cookies"]:
                    udemy.fetch_cookies()
                # Then try saved credentials
                elif udemy.settings["email"] and udemy.settings["password"]:
                    udemy.manual_login(udemy.settings["email"], udemy.settings["password"])
                # Finally ask for credentials
                else:
                    email = console.input("[cyan]Email: [/cyan]")
                    password = console.input("[cyan]Password: [/cyan]")
                    udemy.manual_login(email, password)
                    udemy.settings["email"], udemy.settings["password"] = email, password
                
                udemy.get_session_info()
                login_successful = True
            except LoginException as e:
                handle_error("Login error", error=e, exit_program=False)
                if udemy.settings["use_browser_cookies"]:
                    udemy.settings["use_browser_cookies"] = False
                else:
                    udemy.settings["email"], udemy.settings["password"] = "", ""

        udemy.save_settings()

        # Validate settings
        if udemy.is_user_dumb():
            console.print("[red]Please select at least one site, language, and category in the settings.[/red]")
            sys.exit(1)

        # Start scraping and enrollment quietly
        scraper = Scraper(udemy.sites)
        # Remove progress bar to prevent display issues
        udemy.progress = None 
        # Use a simpler scraping function
        udemy.scraped_data = []
        for site in udemy.sites:
            code_name = scraper_dict[site]
            threading.Thread(target=getattr(scraper, code_name), daemon=True).start()
            time.sleep(0.1)
        # Wait for all scrapers to finish
        while not all(getattr(scraper, f"{scraper_dict[site]}_done") for site in udemy.sites):
            time.sleep(0.5)
        # Combine results
        for site in udemy.sites:
            courses = getattr(scraper, f"{scraper_dict[site]}_data")
            for course in courses:
                course.site = site
                udemy.scraped_data.append(course)
        
        try:
            udemy.start_new_enroll()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            handle_error("An unexpected error occurred", error=e, exit_program=False)

        # Just show done message after completion
        console.print("[green]Done![/green]")

        # Properly terminate server-side session
        try:
            udemy.logout()
        except Exception as e:
            handle_error("Error during logout", error=e, exit_program=False)

    except Exception as e:
        handle_error("A critical error occurred", error=e, exit_program=True)
