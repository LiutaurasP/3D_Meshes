from generate_mesh import make_inspection

def main():
    # Generate two synthetic inspections
    inspection_a = make_inspection(changed=False)
    inspection_b = make_inspection(changed=True)

    # Print basic information
    print("Inspection A:", inspection_a)
    print("Inspection B:", inspection_b)


if __name__ == "__main__":
    main()
