from app.manifest import environment_report, write_manifest

if __name__ == "__main__":
    rows = write_manifest()
    environment_report()
    print(f"Read-only source scan complete: {len(rows)} files")
